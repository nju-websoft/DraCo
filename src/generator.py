import os
import json

try:
    from .graph import tGraph
    from .extract_dataflow import PythonParser
    from .node_prompt import projectSearcher
    from .tokenizer import ModelTokenizer
    from .utils import MAX_HOP, ONLY_DEF, ENABLE_DOCSTRING, LAST_K_LINES
except:
    from graph import tGraph
    from extract_dataflow import PythonParser
    from node_prompt import projectSearcher
    from tokenizer import ModelTokenizer
    from utils import MAX_HOP, ONLY_DEF, ENABLE_DOCSTRING, LAST_K_LINES


class Generator(object):
    def __init__(self, proj_dir, info_dir, model):
        self.parser = PythonParser()
        self.proj_dir = os.path.abspath(proj_dir)
        self.info_dir = os.path.abspath(info_dir)

        self.searcher = projectSearcher()
        self.tokenizer = ModelTokenizer(model)

        self.project = None
        self.proj_info = None
    

    def _set_project(self, project):
        if project == self.project:
            return

        info_file = os.path.join(self.info_dir, f'{project}.json')
        if not os.path.isfile(info_file):
            print(f'Unknown package {project} in {self.info_dir}')
            return
        
        self.project = project
        with open(info_file, 'r') as f:
            self.proj_info = json.load(f)
    

    def set_pyfile(self, project, fpath):
        self._set_project(project)
        
        # remove current file
        if fpath in self.proj_info:
            proj_info = {k:v for k,v in self.proj_info.items() if k != fpath}
        else:
            proj_info = self.proj_info
        
        dir_path = os.path.join(self.proj_dir, project)
        if os.path.isdir(dir_path):
            content = list(os.listdir(dir_path))
            if len(content) == 1:
                dir_path = os.path.join(dir_path, content[0])
        
        self.searcher.set_proj(dir_path, proj_info)
    

    def _get_module_name(self, fpath):
        if fpath.endswith('.py'):
            fpath = fpath[:-3]
            if fpath.endswith('__init__'):
                fpath = fpath[:-8]

        fpath = fpath.rstrip(os.sep)
        return fpath[len(self.searcher.proj_dir):].replace(os.sep, '.')


    def get_suffix(self, fpath):
        return self.searcher.get_path_comment(fpath)
    

    def sort_by_lineno(self, src_list, reverse=True):
        '''
        src_list: [(anything, ..., lineno)]
        Return: sorted list without lineno
        '''
        sorted_list = sorted(src_list, key=lambda x:x[-1], reverse=reverse)
        return [x[:-1] for x in sorted_list]


    def get_cross_file_nodes(self, fpath, imported_info):
        node_list = []
        for item in imported_info:
            find_info = self.searcher.is_local_import(fpath, item)
            if find_info is not None:
                if find_info[1] is None:
                    find_info = (find_info[0], '')
                else:
                    find_info = tuple(find_info)
                
                if find_info not in node_list:
                    node_list.append(find_info)
        
        return node_list
    

    def get_prompt(self, node_list):
        return self.searcher.get_prompt(node_list, MAX_HOP, ONLY_DEF, ENABLE_DOCSTRING)


    def retrieve_prompt(self, project, fpath, source_code):
        '''
        last k lines + other import nodes until maximum length, only type-sensitive rels for k lines
        '''
        self.set_pyfile(project, fpath)

        fpath = self._get_module_name(fpath)

        self.parser.parse(source_code)

        limit_assign = True
        graph = tGraph(self.parser.DFG)

        # check cross-file imports
        cross_import_nodes = set()
        for k, v in graph.node_dict.items():
            if v.node_type == 'import' and self.searcher.is_local_import(fpath, (v.module, v.name)) is not None:
                cross_import_nodes.add(k)

        # Part1: imported information from last k lines
        variable_nodes = graph.get_last_k_lines(LAST_K_LINES)
        related_nodes = graph.get_related_nodes(variable_nodes, reverse=True, limit_assign=limit_assign)
        proj_nodes = set(related_nodes) & cross_import_nodes
        
        # subgraph
        related_nodes = graph.get_related_nodes(variable_nodes, reverse=True, end_nodes=proj_nodes, limit_assign=limit_assign)
        # create subgraph
        subgraph = graph.get_assign_subgraph(related_nodes, proj_nodes)
        # all nodes with module info in subgraph
        imported_dict = {}
        for k, v in subgraph.module_info.items():
            for item in v:
                # (module, name)
                info = tuple(item[:2])
                # pos: smaller is better (the lineno of import statements)
                pos = (0, item[2])
                if info not in imported_dict:
                    imported_dict[info] = pos
                else:
                    imported_dict[info] = min(imported_dict[info], pos)

        # Part2: other import nodes
        other_proj_nodes = cross_import_nodes - proj_nodes
        related_nodes = graph.get_related_nodes(other_proj_nodes, reverse=False, end_nodes=None, limit_assign=True)
        # create subgraph
        subgraph = graph.get_assign_subgraph(related_nodes, other_proj_nodes)
        # all nodes with module info in subgraph
        other_imported_dict = {}
        for k, v in subgraph.module_info.items():
            for item in v:
                # (module, name)
                info = tuple(item[:2])
                # pos: smaller is better (the lineno of import statements)
                pos = (1, item[2])
                if info not in other_imported_dict:
                    other_imported_dict[info] = pos
                else:
                    other_imported_dict[info] = min(other_imported_dict[info], pos)
        
        # get maximum prompt length
        suffix = self.get_suffix(fpath)
        max_prompt_length = self.tokenizer.cal_prompt_max_length(source_code, suffix)

        # prompt from Part 1
        imported_info = self.sort_by_lineno([(k[0], k[1], v) for k, v in imported_dict.items()])
        node_list = self.get_cross_file_nodes(fpath, imported_info)
        prompt = self.get_prompt(node_list)

        # other imported info from Part 2
        sorted_others = sorted(other_imported_dict, key=lambda x:other_imported_dict[x])
        for item in sorted_others:
            if item not in imported_dict:
                imported_dict[item] = other_imported_dict[item]
            else:
                imported_dict[item] = min(imported_dict[item], other_imported_dict[item])

            imported_info = self.sort_by_lineno([(k[0], k[1], v) for k, v in imported_dict.items()])
            node_list = self.get_cross_file_nodes(fpath, imported_info)
            new_prompt = self.get_prompt(node_list)
            if len(prompt) > 0 and not self.tokenizer.judge_prompt(new_prompt, max_prompt_length):
                break
            
            prompt = new_prompt
        
        return self.tokenizer.truncate_concat(source_code, prompt, suffix)