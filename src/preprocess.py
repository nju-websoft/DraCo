import os
import re
import json
from pyfile_parse import PythonParser
from node_prompt import projectSearcher
from utils import DS_REPO_DIR, DS_FILE, DS_GRAPH_DIR


class projectParser(object):
    def __init__(self):
        self.py_parser = PythonParser()
        self.iden_pattern = re.compile(r'[^\w\-]')

        self.proj_searcher = projectSearcher()

        self.proj_dir = None
        self.parse_res = None
    

    def set_proj_dir(self, dir_path):
        if not dir_path.endswith(os.sep):
            self.proj_dir = dir_path + os.sep
        else:
            self.proj_dir = dir_path


    def retain_project_rels(self):
        '''
        retain the useful relationships
        '''
        for module, file_info in self.parse_res.items():
            for name, info_dict in file_info.items():
                cls = info_dict.get("in_class", None)

                # intra-file relations
                rels = info_dict.get("rels", None)
                if rels is not None:
                    del_index = []
                    for i, item in enumerate(rels):
                        # item: [name, type]
                        find_info = self.proj_searcher.name_in_file(item[0], list(file_info), name, cls)
                        if find_info is None:
                            del_index.append(i)
                        else:
                            # modify
                            info_dict["rels"][i] = [find_info[0], find_info[1], item[1]]
                    
                    # delete
                    for index in reversed(del_index):
                        info_dict["rels"].pop(index)
                    
                    if len(info_dict["rels"]) == 0:
                        info_dict.pop("rels")

                # cross-file relations
                imported_info = info_dict.get("import", None)
                if info_dict["type"] == 'Variable' and imported_info is not None:
                    judge_res = self.proj_searcher.is_local_import(module, imported_info)
                    if judge_res is None:
                        info_dict.pop("import")
                    else:
                        info_dict["import"] = judge_res



    def _get_all_module_path(self, target_path):
        if not os.path.isdir(target_path):
            return {}

        dir_list = [target_path,]
        py_dict = {}
        while len(dir_list) > 0:
            py_dir = dir_list.pop()
            py_dict[py_dir] = set()
            for item in os.listdir(py_dir):
                fpath = os.path.join(py_dir, item)
                if os.path.isdir(fpath):
                    if re.search(self.iden_pattern, item) is None:
                        dir_list.append(fpath)
                        py_dict[py_dir].add(fpath)
                elif os.path.isfile(fpath) and fpath.endswith('.py'):
                    if re.search(self.iden_pattern, item[:-3]) is None:
                        py_dict[py_dir].add(fpath)
        
        return py_dict


    def _get_module_name(self, fpath):
        if fpath.endswith('.py'):
            fpath = fpath[:-3]
            if fpath.endswith('__init__'):
                fpath = fpath[:-8]

        fpath = fpath.rstrip(os.sep)
        return fpath[len(self.proj_dir):].replace(os.sep, '.')


    def parse_dir(self, pkg_dir):
        '''
        Return: {module: {
            name: {
                "type": str,                         # type: "Module", "Class", "Function", "Variable"
                "def": str,
                "docstring": str (optional),
                "body": str (optional),
                "sline": int (optional),
                "in_class": str (optional),
                "in_init": bool (optional),
                "rels": [[name:str, suffix:str, type:str], ],    # type: "Assign", "Hint", "Rhint", "Inherit"
                "import": [module:str, name:str]     # "Import"
            }
            }}
        '''
        self.set_proj_dir(pkg_dir)
        py_dict = self._get_all_module_path(pkg_dir)
        
        # order: dir, __init__.py, .py
        module_dict = {}
        # dir
        for dir_path in py_dict:
            module = self._get_module_name(dir_path)
            if len(module) > 0:
                module_dict[module] = [dir_path,]
        
        # pyfiles
        init_files = set()
        pyfiles = set()
        for py_set in py_dict.values():
            for fpath in py_set:
                if fpath.endswith(os.sep + '__init__.py'):
                    init_files.add(fpath)
                else:
                    pyfiles.add(fpath)
        
        # __init__.py
        for fpath in init_files:
            module = self._get_module_name(fpath)
            if len(module) > 0:
                if module in module_dict:
                    module_dict[module].append(fpath)
                else:
                    module_dict[module] = [fpath,]
        
        # .py
        for fpath in pyfiles:
            module = self._get_module_name(fpath)
            if len(module) > 0:
                if module in module_dict:
                    module_dict[module].append(fpath)
                else:
                    module_dict[module] = [fpath,]
        
        self.parse_res = {}
        for module, path_list in module_dict.items():
            info_dict = {}
            for fpath in path_list:
                if fpath in py_dict:
                    # dir
                    for item in py_dict[fpath]:
                        submodule = self._get_module_name(item)
                        if submodule != module:
                            # exclude __init__.py
                            info_dict[submodule] = {
                                "type": "Module",
                                "import": [submodule, None]
                            }
                else:
                    # pyfiles
                    info_dict.update(self.py_parser.parse(fpath))
                    break
            
            if len(info_dict) > 0:
                self.parse_res[module] = info_dict

        self.proj_searcher.set_proj(pkg_dir, self.parse_res)
        # connect the files
        self.retain_project_rels()

        return self.parse_res



if __name__ == '__main__':

    with open(DS_FILE, 'r') as f:
        ds = [json.loads(line) for line in f.readlines()]
    
    pkg_set = set([x['pkg'] for x in ds])
    print(f'There are {len(pkg_set)} repositories in ReccEval.')

    project_parser = projectParser()

    if not os.path.isdir(DS_GRAPH_DIR):
        os.mkdir(DS_GRAPH_DIR)

    for item in os.listdir(DS_REPO_DIR):
        if item not in pkg_set:
            continue
        
        dir_path = os.path.join(DS_REPO_DIR, item)
        if os.path.isdir(dir_path):
            
            content = list(os.listdir(dir_path))
            if len(content) > 1:
                info = project_parser.parse_dir(dir_path)
            else:
                # package/package-version/
                dist_path = os.path.join(dir_path, content[0])
                info = project_parser.parse_dir(dist_path)

            with open(os.path.join(DS_GRAPH_DIR, f'{item}.json'), 'w') as f:
                json.dump(info, f)
    
    print(f'Generate repo-specific context graph for {len(os.listdir(DS_GRAPH_DIR))} repositories.')