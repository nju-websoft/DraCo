import os
import json
from itertools import groupby


class projectSearcher(object):
    def __init__(self) -> None:
        self.proj_dir = None
        self.proj_info = None

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'standard_modules.json'), 'r') as f:
            self.standard_modules = json.load(f)
    

    def set_proj(self, proj_dir, proj_info):
        if proj_dir.endswith(os.sep):
            self.proj_dir = proj_dir
        else:
            self.proj_dir = proj_dir + os.sep

        self.proj_info = proj_info


    def name_in_file(self, name, avail_list, src_name=None, cls=None):
        '''
        Find the available name in current file
        '''

        if name.startswith('self.') and cls:
            name = f'{cls}{name[4:]}'

        for item in sorted(avail_list, key=lambda x:len(x.split('.')), reverse=True):
            if src_name is None or item != src_name:
                if name == item:
                    return item, None
                
                elif name.startswith(f'{item}.'):
                    return item, name[len(item)+1:]
        
        return None


    def is_local_import(self, fpath, imported_info):
        '''
        Judge if module.name is imported from current project
        '''
        module, name = imported_info

        if name is not None:
            module = module.rstrip('.')

            find_info = self._check_local_import(fpath, (f'{module}.{name}', None))
            if find_info is not None:
                return find_info

            split_info = name.split('.')
            for i in range(1, len(split_info)):
                left_name = '.'.join(split_info[:-i])
                right_name = '.'.join(split_info[-i:])
                find_info = self._check_local_import(fpath, (f'{module}.{left_name}', right_name))
                if find_info is not None:
                    return find_info
        
        return self._check_local_import(fpath, imported_info)
    

    def get_distance_fpaths(self, src_path, target_path):
        src_split = src_path.split('.')
        target_split = target_path.split('.')

        src_len = len(src_split)
        target_len = len(target_split)
        common_len = min(src_len, target_len)

        equal_len = 0
        while equal_len < common_len and src_split[equal_len] == target_split[equal_len]:
            equal_len += 1
        
        return src_len + target_len - 2 * equal_len


    def _check_local_import(self, fpath, imported_info):
        '''
        Judge if module.name is imported from current project
        '''
        module, name = imported_info

        if module.startswith('.'):
            # relative import
            module = module.lstrip('.')
        else:
            top_module = module.split('.')[0]
            if top_module in self.standard_modules:
                # Python standard module
                return None
        
        candidates_modules = [x for x in self.proj_info if x == module or x.endswith('.'+module)]
        nums = len(candidates_modules)
        if nums > 0:
            if nums > 1:
                # sort by distance
                candidates_modules.sort(key=lambda x:self.get_distance_fpaths(x, fpath))
            
            for item in candidates_modules:
                if name is None:
                    return [item, name]
                else:
                    find_info = self.name_in_file(name, list(self.proj_info[item]))
                    if find_info is not None:
                        return [item, find_info[0]]
        
        return None


    def _get_indent(self, def_stat):
        return def_stat.split('\n')[-1]
    

    def _get_module_prompt(self, file_info, name_set, only_def=True, enable_docstring=True):
        prompt_list = []
        if enable_docstring:
            docstring = file_info[''].get('docstring', None)
            if docstring:
                prompt_list.append(docstring)

        global_names = [k for k, v in file_info.items() if not v.get('in_class', False)]
        global_names.remove('')
        global_names.sort(key=lambda x:file_info[x].get('sline', -1))

        for sline, name_list in groupby(global_names, key=lambda x:file_info[x].get('sline', -1)):
            name_list = list(name_list)

            if sline == -1:
                submodules = ', '.join(name_list)
                if not only_def:
                    submodules = 'import ' + submodules
                prompt_list.append(submodules)

            else:
                if len(name_list) > 1:
                    for name in name_list:
                        if file_info[name]['type'] != 'Variable':
                            name_list = [name, ]
                            break
                        # assert file_info[name]['type'] == 'Variable'
                
                name = name_list[0]
                name_info = file_info[name]
                name_type = name_info['type']

                if name_type == 'Variable':
                    if any([x in name_set for x in name_list]):
                        prompt_list.append(self._get_variable_prompt(file_info, name_list, False))
                    else:
                        prompt_list.append(self._get_variable_prompt(file_info, name_list, only_def))
                
                elif name_type == 'Function':
                    prompt_list.append(self._get_function_prompt(name_info, only_def, enable_docstring))
                
                elif name_type == 'Class':
                    tmp_set = name_set | {name}
                    prompt_list.append(self._get_class_prompt(file_info, name, {}, tmp_set, only_def=only_def, enable_docstring=enable_docstring))

        prompt_list = [x.rstrip() for x in prompt_list]
        return '\n'.join(prompt_list)


    def _get_class_prompt(self, file_info, cls_name, cls_dict, name_set, only_def=True, enable_docstring=True):
        '''
        cls_name: class name
        cls_dict: {cls: member_names}
        name_set: required names
        '''

        def_content = file_info[cls_name]['def']
        cls_indent = self._get_indent(def_content)

        prompt_list = [def_content]
        if enable_docstring:
            docstring = file_info[cls_name].get('docstring', None)
            if docstring:
                prompt_list.append(docstring)

        if cls_name in name_set:
            # the whole class

            member_names = [k for k,v in file_info.items() if v.get('in_class', None) == cls_name]
            member_names.sort(key=lambda x:file_info[x]['sline'])

            for sline, name_list in groupby(member_names, key=lambda x:file_info[x]['sline']):
                name_list = list(name_list)
                if len(name_list) > 1:
                    for name in name_list:
                        if file_info[name]['type'] != 'Variable':
                            name_list = [name, ]
                            break
                        # assert file_info[name]['type'] == 'Variable'
                
                name = name_list[0]
                name_info = file_info[name]
                name_type = name_info['type']

                if name_type == 'Variable':
                    if any([x in name_set for x in name_list]):
                        prompt_list.append(self._get_variable_prompt(file_info, name_list, False))
                    else:
                        prompt_list.append(self._get_variable_prompt(file_info, name_list, only_def))
                
                elif name_type == 'Function':
                    prompt_list.append(self._get_function_prompt(name_info, only_def, enable_docstring))
                
                elif name_type == 'Class':
                    prompt_list.append(self._get_class_prompt(file_info, name, cls_dict, name_set | {name}, only_def, enable_docstring))

        else:
            # specific names
            member_names = cls_dict.get(cls_name, [])
            init_func = f'{cls_name}.__init__'
            has_init = init_func in member_names
            member_names = sorted(member_names, key=lambda x:file_info[x]['sline'])

            for sline, name_list in groupby(member_names, key=lambda x:file_info[x]['sline']):
                name_list = list(name_list)
                if len(name_list) > 1:
                    for name in name_list:
                        if file_info[name]['type'] != 'Variable':
                            name_list = [name, ]
                            break
                        # assert file_info[name]['type'] == 'Variable'
                
                name = name_list[0]
                name_info = file_info[name]
                name_type = name_info['type']

                if name_type == 'Variable':
                    if not has_init and name_info.get('in_init', False):
                        # variable is in __init__()
                        has_init = True
                        prompt_list.append(self._get_function_prompt(file_info[init_func], True, False))

                    if any([x in name_set for x in name_list]):
                        prompt_list.append(self._get_variable_prompt(file_info, name_list, False))
                    else:
                        prompt_list.append(self._get_variable_prompt(file_info, name_list, only_def))
                
                elif name_type == 'Function':
                    prompt_list.append(self._get_function_prompt(name_info, only_def, enable_docstring))
                
                elif name_type == 'Class':
                    prompt_list.append(self._get_class_prompt(file_info, name, cls_dict, name_set, only_def, enable_docstring))
        

        prompt_list = [x.rstrip() for x in prompt_list]
        return f'\n{cls_indent}'.join(prompt_list)


    def _get_function_prompt(self, node_info, only_def=True, enable_docstring=True):
        prompt = node_info['def']
        if not only_def:
            prompt += node_info['body']
        elif enable_docstring:
            prompt += node_info.get('docstring', '')
        
        return prompt


    def _get_variable_prompt(self, file_info, name_list, only_def=True):
        if not only_def:
            name_info = file_info[name_list[0]]
            in_init = name_info.get('in_init', False)
            if in_init:
                return '    ' + name_info['def']
            else:
                return name_info['def']
        
        ret = []
        for name in name_list:
            name_info = file_info[name]

            cls = name_info.get('in_class', None)
            if cls:
                name = name[len(cls)+1:]
            
            if name_info.get('in_init', False):
                name = '    self.' + name
            
            ret.append(name)
        
        return ', '.join(ret)


    def get_path_comment(self, fpath):
        return f"# {fpath.replace('.', os.sep)}.py\n"


    def get_prompt4names(self, fpath, name_set, only_def=True, enable_docstring=True):
        '''
        Merge the names in same statement, function, class, module (the items in name_set exist)
        '''
        file_info = self.proj_info.get(fpath, None)
        if file_info is None:
            return None
        
        path_comment = self.get_path_comment(fpath)

        if '' in name_set or None in name_set:
            # the whole module
            return path_comment + self._get_module_prompt(file_info, name_set, only_def, enable_docstring)

        cls_dict = {}
        global_names = set()
        for name in name_set:
            cls = file_info[name].get('in_class', None)
            while cls is not None:
                # name is in a class
                if cls not in cls_dict:
                    cls_dict[cls] = {name}
                else:
                    cls_dict[cls].add(name)
                
                name = cls
                cls = file_info[name].get('in_class', None)
            
            global_names.add(name)
        
        # global
        prompt_list = []

        global_names = sorted(global_names, key=lambda x:file_info[x].get('sline', -1))
        for sline, name_list in groupby(global_names, key=lambda x:file_info[x].get('sline', -1)):
            name_list = list(name_list)

            if sline == -1:
                # submodule, which is not in the source code
                submodules = ', '.join(name_list)
                if not only_def:
                    submodules = 'import ' + submodules
                prompt_list.append(submodules)

            else:
                if len(name_list) > 1:
                    for name in name_list:
                        if file_info[name]['type'] != 'Variable':
                            name_list = [name, ]
                            break
                        # assert file_info[name]['type'] == 'Variable'
                
                name = name_list[0]
                name_info = file_info[name]
                name_type = name_info['type']

                if name_type == 'Variable':
                    # stats for explicit variable
                    prompt_list.append(self._get_variable_prompt(file_info, name_list, False))
                
                elif name_type == 'Function':
                    prompt_list.append(self._get_function_prompt(name_info, only_def, enable_docstring))
                
                elif name_type == 'Class':
                    prompt_list.append(self._get_class_prompt(file_info, name, cls_dict, name_set, only_def=only_def, enable_docstring=enable_docstring))

        prompt_list = [x.rstrip() for x in prompt_list]
        return path_comment + '\n'.join(prompt_list)


    def pseudo_topo_sort(self, fpath_set, file_edges, fpath_order):
        '''
        file_edges: {fpath: [fpath]}
        fpath_order: reversed, significance decreases progressively
        '''
        in_table = {}
        out_table = {}
        for item in fpath_set:
            if item not in in_table:
                in_table[item] = []
            if item not in out_table:
                out_table[item] = []

            for x in file_edges.get(item, []):
                if x not in fpath_set:
                    continue

                out_table[item].append(x)
                if x not in in_table:
                    in_table[x] = [item]
                else:
                    in_table[x].append(item)

        sort_list = []
        while len(in_table) > 0:
            node_list = list(in_table)

            # choice the most significant fpath in topo order
            min_index = 0
            min_degree = len(in_table[node_list[min_index]])
            for i in range(1, len(node_list)):
                item = node_list[i]

                in_degree = len(in_table[item])
                if in_degree < min_degree:
                    # in degree
                    min_index = i
                    min_degree = in_degree
                elif in_degree == min_degree:
                    if node_list[min_index] in fpath_order and item in fpath_order:
                        # keep to the order
                        if fpath_order.index(item) < fpath_order.index(node_list[min_index]):
                            min_index = i
                    elif node_list[min_index] not in fpath_order and item not in fpath_order:
                        # compare string
                        if item < node_list[min_index]:
                            min_index = i
                    else:
                        if item not in fpath_order:
                            min_index = i
            
            item = node_list[min_index]
            sort_list.append(item)

            for x in out_table.pop(item):
                in_table[x].remove(item)
            
            for x in in_table.pop(item):
                out_table[x].remove(item)
        
        sort_list = list(reversed(sort_list))
        
        return sort_list


    def depthFirstSearch(self, fpath, name, max_hop=None):
        '''
        DFS from self.proj_info[fpath][name]
        '''
        node_dict = {}  # {fpath: set(name)}
        file_edges = {} # {fpath: [fpath]}

        self.dfs(fpath, name, 0, node_dict, file_edges, max_hop)

        return node_dict, file_edges
    

    def dfs(self, fpath, name, depth, node_dict, file_edges, max_hop):

        if fpath not in self.proj_info or name not in self.proj_info[fpath]:
            return

        if fpath in node_dict and name in node_dict[fpath]:
            # already visit
            return
        
        node_info = self.proj_info[fpath][name]
        if fpath not in node_dict:
            node_dict[fpath] = {name}
        else:
            node_dict[fpath].add(name)
        
        if max_hop is not None and depth+1 > max_hop:
            # exceed the max hop
            return

        if 'import' in node_info:
            t_fpath, t_name = node_info['import']
            if t_fpath not in file_edges:
                file_edges[t_fpath] = []

            if fpath not in file_edges:
                file_edges[fpath] = [t_fpath]
            else:
                file_edges[fpath].append(t_fpath)
            
            self.dfs(t_fpath, t_name, depth+1, node_dict, file_edges, max_hop)
        
        if 'rels' in node_info:
            for item in node_info['rels']:
                t_name = item[0]
                self.dfs(fpath, t_name, depth+1, node_dict, file_edges, max_hop)
    

    def get_prompt(self, node_list, max_hop=None, only_def=True, enable_docstring=True):
        '''
        node_list: [(fpath, name)]
        '''
        node_dict = {}  # {fpath: set(name)}
        file_edges = {} # {fpath: [fpath]}

        fpath_order = []

        for fpath, name in node_list:
            if fpath not in fpath_order:
                fpath_order.append(fpath)

            tmp_nodes, tmp_edges = self.depthFirstSearch(fpath, name, max_hop)
            for k, v in tmp_nodes.items():
                if k not in node_dict:
                    node_dict[k] = v
                else:
                    node_dict[k].update(v)
            
            for k, v in tmp_edges.items():
                if k not in file_edges:
                    file_edges[k] = v
                else:
                    file_edges[k].extend(v)

        sorted_files = self.pseudo_topo_sort(set(node_dict), file_edges, fpath_order)

        prompt_list = []
        for fpath in sorted_files:
            prompt_list.append(self.get_prompt4names(fpath, node_dict[fpath], only_def, enable_docstring))
        
        # replece the docsting
        return '\n\n'.join(prompt_list).replace("'''", '"""')