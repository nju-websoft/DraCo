import os
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

# import networkx as nx

class NodeType():
    IMPORT = 'import'
    VARIABLE = 'variable'


class EdgeType:
    ASSIGN = 'assign'
    ASSIGN_FROM = 'assignfrom'
    PARAM = 'param'
    FOR_IN_CLAUSE = 'forin'
    AS_PATTERN = 'as'
    PARENT_CLASS = 'successor'
    COMES_FROM = 'comesfrom'
    # Hints
    MAIN_TYPE = 'type'
    RELATED_TYPE = 'related_type'


class Leaf():
    def __init__(self, index, node, var_name, node_type) -> None:
        self.index = index
        self.ast_node = node
        self.var_name = var_name
        self.node_type = node_type

        self.module = None
        self.name = None 

class DataflowGraph():
    def __init__(self) -> None:
        self.leaf_cnt = 0
        self.dfg_nodes = {}
        self.dfg_edges = {EdgeType.__dict__[attr]:[] for attr in dir(EdgeType) if not attr.startswith('_')}

    """
    # Install networkx and pydot for visualization

    def write_to_dot(graph, filename):
        g = nx.nx_pydot.to_pydot(graph)
        nx.nx_pydot.write_dot(graph, filename)
        return g

    def visualize(self, dot_file):
        G = nx.DiGraph()
        for k, v in self.dfg_nodes.items():
            lineno = v.ast_node.start_point[0]
            label_name = v.var_name
            
            if ':' in label_name:
                print(str(lineno+1)+'_'+label_name)
            G.add_node(k, label=str(k)+'_'+str(lineno+1)+'_'+label_name)

        visual_dict = {'assign':'A', 'assignfrom':'AF', 'param':'P', 'forin':'FI', 'as':'AS', 'successor':'S', 'comesfrom':'CF', 'type':'T', 'related_type':'RT'}

        for type, edges in self.dfg_edges.items():
            for edge in edges:
                G.add_edge(edge[1], edge[0], label=visual_dict[type])
        
        self.Graph = G
        
        # nx.set_edge_attributes(G, 'computes', 'edge_type')
        nx.set_edge_attributes(G, '#00A3FF', 'color')
        
        # edge_labels = nx.get_edge_attributes(G, 'name')
        # nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels)

        nx.nx_pydot.to_pydot(G)
        nx.nx_pydot.write_dot(G, dot_file)
        return G
    """

    def create_dfg_node(self, ast_node, var_name, node_type, module=None, name=None):
        node_idx = self.leaf_cnt

        dfg_node = Leaf(self.leaf_cnt, ast_node, var_name, node_type)
        self.dfg_nodes[node_idx] = dfg_node
        self.leaf_cnt += 1
        if node_type == NodeType.IMPORT:
            dfg_node.module = module
            dfg_node.name = name
        return dfg_node


class PythonParser():
    def __init__(self) -> None:

        PY_LANGUAGE = Language(tspython.language())
        self.parser = Parser(PY_LANGUAGE)

        self.class_name = []
        self.class_name_node_mapping = {}
        self.class_attri_map = {}
        self.not_linked_node = {}
        self.class_methods = {}
        self.global_states = {}
        self.global_var_name_ast_id = set()

    def parse_file(self, filename):
        src_code = ''
        with open(filename) as f:
            src_code = f.read()

        self.parse(src_code)

    def clear(self):
        self.class_name = []
        self.class_name_node_mapping = {}
        self.class_attri_map = {} 
        self.not_linked_node = {}
        self.class_methods = {}
        self.global_states = {}
        self.global_var_name_ast_id = set()

    def parse(self, src_code):
        self.clear()

        self.root_node = self.parser.parse(bytes(src_code, "utf8")).root_node
        self.DFG = DataflowGraph()

        states = {}
        self.walk_ast(self.root_node, states)

    def walk_ast(self, node, states):
        node_type = node.type
        
        if self._is_variable(node):
            identify_node = self._deal_variable(node, states, add_flag=False)

        elif node_type in ['attribute', 'call', 'subscript']:
            identify_node, param_nodes, slice_nodes = self._deal_attribute_call_subscript(node=node, states=states, add_flag=False)
            
        elif node_type in ['assignment', 'augmented_assignment']:
            self._deal_assignment(node, states)
  
        elif node_type in ['for_statement', 'for_in_clause']:
            self._deal_for_statement(node, states)
        
        elif node_type in ['as_pattern']:
            self._deal_as_pattern(node, states)

        elif node_type in ['function_definition']:
            self._deal_function_definition(node, states)
        
        elif node_type in ['class_definition']:
            self._deal_class_definition(node, states)

        elif node_type in ['import_statement', 'import_from_statement']:
            self._deal_import_statement(node, states)
        
        else:
            for child in node.children:
                self.walk_ast(child, states)

        return 
    

    def _deal_function_definition(self, node, states):
        
        function_name_node = node.child_by_field_name('name')
        parameters_nodes = node.child_by_field_name('parameters')
        return_type_nodes = node.child_by_field_name('return_type')

        if self.class_name:
            cur_class_name = self.class_name[-1]
            function_name = 'self.' + function_name_node.text.decode()
            function_dfg_node = self.create_node(function_name_node, function_name, states, check_flag=False)   
        else:
            function_name = function_name_node.text.decode()
            function_dfg_node = self.create_node(function_name_node, function_name, states, check_flag=False)
        
        states_backup = states.copy()
        
        param_dfg_nodes = self._deal_parameters(parameters_nodes, states_backup)
        
        if return_type_nodes:
            main_type, related_type= self._deal_type_hint(return_type_nodes, states_backup)
            for m_type in main_type:
                self.DFG.dfg_edges[EdgeType.MAIN_TYPE].append((m_type.index, function_dfg_node.index))
            
            for r_type in related_type:
                self.DFG.dfg_edges[EdgeType.RELATED_TYPE].append((r_type.index, function_dfg_node.index))

        flag = False
        for child in node.children:
            if flag:
                self.walk_ast(child, states_backup)
            if child.type == ':':
                flag = True
        
        if function_name == 'self.__init__':
            variable_in_init = list(states_backup.keys())
            for var in variable_in_init:
                if var.startswith('self.'):
                    self.class_attri_map[cur_class_name][var] = states_backup[var]

        if function_name in self.class_methods.keys():
            self.class_methods[function_name] = function_dfg_node.index
        
    def _deal_class_definition(self, node, states):
        name_node = node.child_by_field_name('name')
        
        super_class_node = node.child_by_field_name('superclasses')
        super_identify_node = None
        if super_class_node:
            for child in super_class_node.named_children:
                if child.type == 'comment':
                    continue
                super_identify_node, _, _ = self._deal_attribute_call_subscript(child, states, add_flag=False)
                
        self.class_name.append(name_node.text.decode()) 
        
        self.class_attri_map[name_node.text.decode()] = {}
        name_dfg_node = self.create_node(name_node, name_node.text.decode(), states, check_flag=False)
        self.class_name_node_mapping[name_node.text.decode()] = name_dfg_node.index
        
        if super_identify_node:
            self.DFG.dfg_edges[EdgeType.PARENT_CLASS].append((name_dfg_node.index, super_identify_node.index))

        self.class_methods = {}
        body_node = node.child_by_field_name('body')
        for item in body_node.children:   
            if item.type == 'decorated_definition':
                item = item.child_by_field_name('definition')
            
            item_type = item.type
            if item_type == 'function_definition':
                function_name = item.child_by_field_name('name').text.decode()
                dict_key = 'self.' + function_name
                self.class_methods[dict_key] = None
            
            elif item_type == 'expression_statement':
                candidate_assign = item.children[0]
                if candidate_assign.type == 'assignment':
                    class_variable_left_hand = candidate_assign.child_by_field_name('left')
                    class_var_name, class_var_node, _ = self._get_left_hand_side(class_variable_left_hand)[0]
                    external_name = '.'.join(self.class_name) + '.' + class_var_name
                    if external_name not in self.global_states.keys():
                        self.global_var_name_ast_id.add(class_var_node.id)
                        self.global_states[external_name] = None

            elif item_type == 'class_definition':
                sub_class_name = item.child_by_field_name('name')
                external_name = '.'.join(self.class_name) + '.' + sub_class_name.text.decode()
                if external_name not in self.global_states.keys():
                    self.global_var_name_ast_id.add(sub_class_name.id)
                    self.global_states[external_name] = None
        
        states_backup = states.copy()
        flag = False
        for child in node.children:
            if flag:
                self.walk_ast(child, states_backup)
            if child.type == ':':
                flag = True

        for k, v in self.class_methods.items():
            if not v:
                continue

            if k not in self.not_linked_node.keys():
                continue
            nodes_to_be_linked = self.not_linked_node[k]
            for node_to_be_linked in nodes_to_be_linked:
                if node_to_be_linked != v:
                    self.DFG.dfg_edges[EdgeType.COMES_FROM].append((node_to_be_linked, v))

        self.class_name.pop()
        self.not_linked_node = {}
        self.class_methods = {}

    def _is_variable(self, node):
        if node.is_named and (len(node.children) == 0 or node.type in ['string','concatenated_string', 'true', 'false', 'integer','float']) and node.type != 'comment':
            return True
        else:
            return False
    
    def _deal_variable(self, node, states, add_flag=True, check_flag=True):
        node_type = node.type
        
        if node_type in ['string','concatenated_string']:
            var_name = 'str'
        
        elif node_type == 'integer':
            var_name = 'int'
        
        elif node_type == 'float':
            var_name = 'float'
        
        elif node_type in ['true', 'false']:
            var_name = 'bool'
        
        elif node_type == 'none':
            var_name = 'none'
        
        else:
            var_name = node.text.decode()
        var_node = self.create_node(node, var_name=var_name, states=states, add_flag=add_flag, check_flag=check_flag)
        return var_node

    def _deal_parameters(self, node, states):
        node_type = node.type
        dfg_nodes = []

        if node_type == 'identifier':
            identifuer_dfg_node = self.create_node(node, node.text.decode(), states, check_flag=False)
            return [identifuer_dfg_node]
        
        elif node_type == 'typed_parameter':
            
            type_node = node.child_by_field_name('type')
            main_type_dfg_node, related_type_dfg_node = self._deal_type_hint(type_node, states)
            
            identify_node, _, _ = self._deal_attribute_call_subscript(node.children[0], states)
            
            for m_node in main_type_dfg_node:
                self.DFG.dfg_edges[EdgeType.MAIN_TYPE].append((identify_node.index, m_node.index))
            
            for r_node in related_type_dfg_node:
                self.DFG.dfg_edges[EdgeType.RELATED_TYPE].append((identify_node.index, r_node.index))

            return [identify_node] + main_type_dfg_node + related_type_dfg_node
        
        elif node_type == 'default_parameter':
            name_node = node.child_by_field_name('name')
            value_node = node.child_by_field_name('value')
            
            identify_nodes, param_nodes, slice_nodes = self._deal_right_hand_side(value_node, states)
            name_dfg_node = self.create_node(name_node, name_node.text.decode(), states)
            
            if identify_nodes:
                if len(slice_nodes) == 0:
                    self.DFG.dfg_edges[EdgeType.ASSIGN].append((name_dfg_node.index, identify_nodes[0].index))
                else:
                    self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((name_dfg_node.index, identify_nodes[0].index))
                
            for p_node in param_nodes:
                self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((name_dfg_node.index, p_node.index))
            for s_node in slice_nodes:
                self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((name_dfg_node.index, s_node.index))
            
            return [name_dfg_node] + identify_nodes + param_nodes + slice_nodes
        
        elif node_type == 'typed_default_parameter':
            name_node = node.child_by_field_name('name')
            type_node = node.child_by_field_name('type')
            value_node = node.child_by_field_name('value')
            
            # type
            type_node = node.child_by_field_name('type')
            main_type_dfg_node, related_type_dfg_node = self._deal_type_hint(type_node, states)
            
            # value
            identify_node, param_nodes, slice_nodes = self._deal_attribute_call_subscript(value_node, states, add_flag=False)
            
            # name
            name_dfg_node = self.create_node(name_node, name_node.text.decode(), states)
            
            # type -> name
            for m_node in main_type_dfg_node:
                self.DFG.dfg_edges[EdgeType.MAIN_TYPE].append((name_dfg_node.index, m_node.index))
            
            for r_node in related_type_dfg_node:
                self.DFG.dfg_edges[EdgeType.RELATED_TYPE].append((name_dfg_node.index, r_node.index))
            
            # value -> name
            if len(slice_nodes) == 0:
                self.DFG.dfg_edges[EdgeType.ASSIGN].append((name_dfg_node.index, identify_node.index))
            else:
                self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((name_dfg_node.index, identify_node.index))
            for p_node in param_nodes:
                self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((name_dfg_node.index, p_node.index))
            for s_node in slice_nodes:
                self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((name_dfg_node.index, s_node.index))
        
            return [name_dfg_node] + main_type_dfg_node + related_type_dfg_node + [identify_node] + param_nodes + slice_nodes
        
        else:
            for child in node.children:
                tmp_nodes = self._deal_parameters(child, states)
                dfg_nodes += tmp_nodes
            
            return dfg_nodes

    def _deal_attribute_call_subscript(self, node, states, add_flag=True, check_flag=True):
        identify_node = None
        param_nodes = []
        slice_nodes = []

        ret_dict = self._deal_primary_expression(node=node)

        for k, v in ret_dict.items():
            if k == 'identifier':
                identify_node = self.create_node(root_node=v[1], var_name=v[0], states=states, add_flag=add_flag, check_flag=check_flag)
            
            if k == 'param':
                for param in v:
                    tmp_param_node = self.create_node(root_node=param[1], var_name=param[0], states=states, add_flag=add_flag, check_flag=check_flag)
                    param_nodes += [tmp_param_node]
            
            if k == 'slice':
                for slice in v:
                    tmp_slice_node = self.create_node(root_node=slice[1], var_name=slice[0], states=states, add_flag=add_flag, check_flag=check_flag)
                    slice_nodes += [tmp_slice_node]
        
        return identify_node, param_nodes, slice_nodes

    def _deal_assignment(self, node, states):
        assign_stack = []
        p = node
        while p and p.type in ['assignment', 'augument_assignment']:
            assign_stack.append(p)
            hint = p.child_by_field_name('type')
            p = p.child_by_field_name('right')
        
        right_nodes = None
        if p:
            right_nodes = [p]

        r_created = set()
        
        while assign_stack:
            p = assign_stack.pop()
            left_nodes = [p.child_by_field_name('left')]
            left_nodes_type = [x.type for x in p.child_by_field_name('left').children]
            if ',' in left_nodes_type:
                left_nodes = [x for x in left_nodes[0].children if x.is_named]

            if right_nodes:
                if not self._is_variable(right_nodes[0]):
                    right_nodes_types = [x.type for x in right_nodes[0].children]
                    if ',' in right_nodes_types:
                        right_nodes = [x for x in right_nodes[0].children if x.is_named]

                if len(left_nodes) == len(right_nodes):
                    for l, r in zip(left_nodes, right_nodes):
                        if r.id not in r_created:
                            identify_nodes_set, param_nodes_set, slice_nodes_set = self._deal_right_hand_side(r, states)
                            r_created.add(r.id)

                        # hints
                        hint_node = p.child_by_field_name('type')
                        main_type_list = []
                        related_type_list = []
                        if hint_node:
                            main_type_list, related_type_list = self._deal_type_hint(hint_node, states)
                        
                        left_main_dfg_nodes, left_slice_dfg_nodes = self._deal_left_hand_side(l, states)

                        #  hint -> left
                        for l_node in left_main_dfg_nodes:
                            for type_node in main_type_list:
                                self.DFG.dfg_edges[EdgeType.MAIN_TYPE].append((l_node.index, type_node.index))
                        
                            for type_node in related_type_list:
                                self.DFG.dfg_edges[EdgeType.RELATED_TYPE].append((l_node.index, type_node.index))

                        # right -> left
                        # AssignRel Judge Condition
                        assign_flag = False
                        if (r.type in ['identifier', 'attribute', 'call'] or self._is_variable(r)) and (l.type in ['identifier', 'attribute', 'call'] or self._is_variable(l)):
                            assign_flag = True
                            
                        for l_node in left_main_dfg_nodes:
                            for i_node in identify_nodes_set:
                                if assign_flag:
                                    self.DFG.dfg_edges[EdgeType.ASSIGN].append((l_node.index, i_node.index))
                                else:
                                    self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((l_node.index, i_node.index))
                            
                            for p_node in param_nodes_set:
                                self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((l_node.index, p_node.index))

                            for s_node in slice_nodes_set:
                                self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((l_node.index, s_node.index))

                elif len(left_nodes) != len(right_nodes):
                    identify_nodes_set, param_nodes_set, slice_nodes_set = [], [], []
                    for r_node in right_nodes:
                        i_nodes, p_nodes, s_nodes = self._deal_right_hand_side(r_node, states)
                        identify_nodes_set += i_nodes
                        param_nodes_set += p_nodes
                        slice_nodes_set += s_nodes

                    left_main_dfg_nodes, left_slice_dfg_nodes = self._deal_left_hand_side(p.child_by_field_name('left'), states)
                    for left_node in left_main_dfg_nodes:
                        for i_node in identify_nodes_set:
                            self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((left_node.index, i_node.index))

                        for p_node in param_nodes_set:
                            self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((left_node.index, p_node.index))
                        
                        for s_node in slice_nodes_set:
                            self.DFG.dfg_edges[EdgeType.ASSIGN_FROM].append((left_node.index, s_node.index))

            else:
                hint_node = p.child_by_field_name('type')
                left_node = p.child_by_field_name('left')
                if not hint_node:
                    left_dfg_nodes, _ = self._deal_left_hand_side(left_node, states)
                    return
                
                main_type_list, related_type_list = self._deal_type_hint(hint_node, states)
                
                left_dfg_nodes, _ = self._deal_left_hand_side(left_node, states)

                for l_node in left_dfg_nodes:
                    for type_node in main_type_list:
                        self.DFG.dfg_edges[EdgeType.MAIN_TYPE].append((l_node.index, type_node.index))
                
                    for type_node in related_type_list:
                        self.DFG.dfg_edges[EdgeType.RELATED_TYPE].append((l_node.index, type_node.index))
                
    def _deal_for_statement(self, node, states):
        left_nodes = node.child_by_field_name('left')
        right_nodes = node.child_by_field_name('right')

        identify_node, param_nodes, slice_nodes = self._deal_attribute_call_subscript(right_nodes, states, add_flag=False)
        right_dfg_nodes = [identify_node] + list(param_nodes) + list(slice_nodes)

        left_dfg_nodes, _ = self._deal_left_hand_side(left_nodes, states) 

        for l_node in left_dfg_nodes:
            for r_node in right_dfg_nodes:
                self.DFG.dfg_edges[EdgeType.FOR_IN_CLAUSE].append((l_node.index, r_node.index))
        
        flag = False
        for child in node.children:
            if flag:
                self.walk_ast(child, states)
            if child.type == ':':
                flag = True
    
    def _deal_as_pattern(self, node, states):

        identify_node, param_nodes, slice_nodes = [], [], []
        for child in node.children:
            if child.type == 'as':
                break
            else:
                identify_node, param_nodes, slice_nodes = self._deal_attribute_call_subscript(child, states, add_flag=False)
        
                alias_name_node = node.child_by_field_name('alias')

        alias_identify_node, _, _ = self._deal_attribute_call_subscript(alias_name_node, states, check_flag=False)
        
        if alias_identify_node is None:
            return
        
        self.DFG.dfg_edges[EdgeType.AS_PATTERN].append((alias_identify_node.index, identify_node.index))
        for p_node in param_nodes:
            self.DFG.dfg_edges[EdgeType.PARAM].append((alias_identify_node.index, p_node.index))
        for s_node in slice_nodes:
            self.DFG.dfg_edges[EdgeType.PARAM].append((alias_identify_node.index, s_node.index))


    def _deal_type_hint(self, node, states):
        main_type_dfg_nodes = []
        related_type_dfg_nodes = []
        
        main_type_list, related_type_list = self._get_type_hint(node)

        for type_name, type_node in main_type_list:
            tmp_node = self.create_node(type_node, type_name, states, add_flag=False) 
            main_type_dfg_nodes.append(tmp_node)
        
        for type_name, type_node in related_type_list:
            tmp_node = self.create_node(type_node, type_name, states, add_flag=False) 
            related_type_dfg_nodes.append(tmp_node)
        
        return main_type_dfg_nodes, related_type_dfg_nodes


    def _get_type_hint(self, node):
        '''
        type: $ => $.expression,
        '''
        main_type = []
        related_type_list = []
        if node.type in ['identifier', 'attribute', 'subscript', 'call']:
            ret_dict = self._deal_primary_expression(node)
            main_type += [ret_dict['identifier']]
            related_type_list += (ret_dict['param'] + ret_dict['slice']) 
        
        elif node.type == 'type' or 'binary_operator':
            for child in node.children:
                sub_main_type, sub_related_type_set = self._get_type_hint(child)
                main_type += sub_main_type
                related_type_list += sub_related_type_set

        return main_type, related_type_list
    
    def _deal_left_hand_side(self, node, states):
        all_left_nodes = self._get_left_hand_side(node)
        left_main_dfg_nodes = []
        left_slice_dfg_nodes = []
        
        for left_node_varname, left_node, node_type in all_left_nodes:
            if node_type in ['variable', 'attribute']:
                tmp_node = self.create_node(left_node, left_node_varname, states, check_flag=False)
                left_main_dfg_nodes.append(tmp_node)
            elif node_type in ['subscript']:
                tmp_node = self.create_node(left_node, left_node_varname, states)
                left_main_dfg_nodes.append(tmp_node)
            elif node_type in ['slice']:
                tmp_node = self.create_node(left_node, left_node_varname, states, add_flag=False)
                left_slice_dfg_nodes.append(tmp_node)
            
        return left_main_dfg_nodes, left_slice_dfg_nodes

    def _get_left_hand_side(self, node):
        '''
        _left_hand_side: $ => choice(
            $.pattern,
            $.pattern_list,
        )
        '''
        ret_nodes = []
            
        if node.type == 'pattern_list':
            for child in node.children:
                child_nodes = self._get_pattern(child)
                ret_nodes += child_nodes
        
        else:
            tmp_node = self._get_pattern(node)
            ret_nodes += tmp_node

        return ret_nodes
    
    def _deal_right_hand_side(self, node, states):
        '''
        _right_hand_side: $ => choice(
            $.expression,
            $.expression_list,
            $.assignment,
            $.augmented_assignment,
            $.yield
        )
        '''
        identify_nodes_set = []
        param_nodes_set = []
        slice_nodes_set = []

        if self._is_variable(node):
            identify_node = self._deal_variable(node, states, add_flag=False)
            identify_nodes_set.append(identify_node)
            
        elif node.type in ['attribute', 'call', 'subscript']:
            identify_node, param_nodes, slice_nodes = self._deal_attribute_call_subscript(node, states, False)
            identify_nodes_set += [identify_node]
            param_nodes_set += param_nodes
            slice_nodes_set += slice_nodes
        
        else:
            for child in node.children:
                identify_node, param_nodes, slice_nodes = self._deal_right_hand_side(child, states)
                identify_nodes_set += identify_node
                param_nodes_set += param_nodes
                slice_nodes_set += slice_nodes
        
        return identify_nodes_set, param_nodes_set, slice_nodes_set

    def _deal_import_statement(self, node, states):
        node_type = node.type

        if node_type == 'import_statement':
            import_list = node.children_by_field_name('name')
            for import_name in import_list:
                self._deal_import_list(import_name, states)

        elif node_type == 'import_from_statement':
            module_name = node.child_by_field_name('module_name')

            children = node.children
            for i in range(3, len(children)):
                child = children[i]
                if child.type != 'wildcard_import':
                    name_dfg_node, alias_dfg_node = self._deal_import_list(child, states, module_name.text.decode())
                                
        elif node_type == 'future_import_statement':
            children = node.children

            for i in range(3, len(children)):
                name_dfg_node, alias_dfg_node = self._deal_import_list(children[i], states, '__future__')


    def _deal_import_list(self, node, states, module_name=None):
        name_dfg_node = alias_dfg_node = None
        # import a, b, c
        if node.type == 'dotted_name':
            if module_name:
                name = node.text.decode()
                name_dfg_node = self.create_import_node(node, name, states, module_name, name)
            
            else:
                module = node.text.decode()
                name_dfg_node = self.create_import_node(node, module, states, module, None)
            return name_dfg_node, None
            
        # import a as b
        elif node.type == 'aliased_import':
            name = node.child_by_field_name('name')
 
            alias = node.child_by_field_name('alias')
            if module_name:
                alias_dfg_node = self.create_import_node(alias, alias.text.decode(), states, module_name, name.text.decode())
            else:
                alias_dfg_node = self.create_import_node(alias, alias.text.decode(), states, name.text.decode(), None)
        
        return name_dfg_node, alias_dfg_node

    def _get_pattern(self, node):
        if self._is_variable(node):
            return [(node.text.decode(), node, 'variable')]
        
        elif node.type in ['attribute']:
            attribute_name, _ = self._deal_primary_expression(node)['identifier']
            return [(attribute_name, node, 'attribute')]

        elif node.type in ['subscript']:
            ret_val = self._deal_primary_expression(node)
            value_name, value_node = ret_val['identifier']
            ret_nodes = [(value_name, value_node, 'subscript')]
            for slice_name, slice_node in ret_val['slice']:
                ret_nodes.append((slice_name, slice_node, 'slice'))
            return ret_nodes
        
        else:
            all_nodes = []
            for child in node.children:
                all_nodes += self._get_pattern(child)
            return all_nodes
        
    def _ret_variable_list(self, node):
        node_type = node.type
        if node_type in ['string','concatenated_string']:
                var_name = 'str'
        
        elif node_type == 'integer':
            var_name = 'int'
        
        elif node_type == 'float':
            var_name = 'float'
        
        elif node_type in ['true', 'false']:
            var_name = 'bool'
        
        elif node_type == 'none':
            var_name = 'none'

        else:
            var_name = node.text.decode()
        return [(var_name, node)]


    def _get_call_augument(self, node):
        node_type = node.type
        if self._is_variable(node=node):
            return self._ret_variable_list(node)
        
        elif node.type == 'keyword_argument':
            ret_nodes = []
            name_node = node.child_by_field_name('name')
            value_node = node.child_by_field_name('value')

            ret_nodes += self._get_call_augument(value_node)
            return ret_nodes
               
        elif node.type in ['attribute', 'subscript', 'call']:
            ret_dict = self._deal_primary_expression(node)
            ret_list = [ret_dict['identifier']] + ret_dict['param'] + ret_dict['slice']
            return ret_list

        else:
            all_nodes = []
            for child in node.children:
                nodes_of_child = self._get_call_augument(child)
                all_nodes += nodes_of_child
            return all_nodes
        
    def _get_all_variables(self, node):
        if self._is_variable(node=node):
            return self._ret_variable_list(node)
        
        else:
            all_nodes = []
            for child in node.children:
                nodes_of_child = self._get_all_variables(child)
                all_nodes += nodes_of_child
            return all_nodes
    
    def _get_subscript_slice(self, node):
        if self._is_variable(node=node):
            return self._ret_variable_list(node)

        elif node.type in ['attribute', 'subscript', 'call']:
            ret_dict = self._deal_primary_expression(node)
            ret_list = [ret_dict['identifier']] + ret_dict['param'] + ret_dict['slice']
            return ret_list
        
        else:
            all_nodes = []
            for child in node.children:
                nodes_of_child = self._get_subscript_slice(child)
                all_nodes += nodes_of_child
            return all_nodes
    
    def _deal_primary_expression(self, node):
        if node is None:
            return {}

        node_type = node.type

        if node_type == 'identifier':
            ret = {'identifier': (node.text.decode(), node),
                   'param': [],
                   'slice': []
            }

        elif node_type == 'attribute':
            object_node = node.child_by_field_name('object')
            attr = node.child_by_field_name('attribute').text.decode()
            
            prefix_dict = self._deal_primary_expression(object_node)
            attribute_fullname = '{}.{}'.format(prefix_dict['identifier'][0], attr)
            
            ret = {'identifier': (attribute_fullname, node), 
                   'param': prefix_dict['param'], 
                   'slice': prefix_dict['slice']
            }

        elif node_type == 'call':
            '''
            call: $ => prec(PREC.call, seq(
                field('function', $.primary_expression),
                field('arguments', choice(
                    $.generator_expression,
                    $.argument_list
                ))
            ))
            '''
            function_node = node.child_by_field_name('function')
            function_node_dict = self._deal_primary_expression(function_node)
            
            param_nodes = self._get_call_augument(node.child_by_field_name('arguments'))
            
            ret = {'identifier':(function_node_dict['identifier'][0], node), 
                   'param': function_node_dict['param'] + param_nodes, 
                   'slice': function_node_dict['slice']
            }

        elif node_type == 'subscript':
            '''
            subscript: $ => prec(PREC.call, seq(
                field('value', $.primary_expression),
                '[',
                commaSep1(field('subscript', choice($.expression, $.slice))),
                optional(','),
                ']'
            ))
            '''
            value_node = node.child_by_field_name('value')
            value_node_dict = self._deal_primary_expression(value_node)

            slices = value_node_dict['slice']
            subscript_nodes = node.children_by_field_name('subscript')
            for subscript_node in subscript_nodes:
                slices += self._get_subscript_slice(subscript_node)
            
            ret = {'identifier':(value_node_dict['identifier'][0], node), 
                   'param': value_node_dict['param'], 
                   'slice': slices
            }
        
        elif node_type == 'string' or node_type == 'concatenated_string':
            ret = {'identifier': ('str', node), 
                   'param': [], 
                   'slice': []
            }

        elif node_type == 'integer':
            ret = {'identifier': ('int', node), 
                   'param': [], 
                   'slice': []
            }

        elif node_type == 'float':
            ret = {'identifier': ('float', node), 
                   'param': [], 
                   'slice': []
            }

        elif node_type == 'true' or node_type == 'false':
            ret = {'identifier': ('bool', node), 
                   'param': [], 
                   'slice': []
            }

        elif node_type == 'list':
            ret = {'identifier': ('list', node), 
                   'param': [], 
                   'slice': []
            }

        elif node_type == 'dictionary' or node_type == 'dictionary_comprehension':
            ret = {'identifier': ('dict', node), 
                   'param': [], 
                   'slice': []
            }

        elif node_type == 'set' or node_type == 'set_comprehension':
            ret = {'identifier': ('set', node), 
                   'param': [], 
                   'slice': []
            }

        elif node_type == 'tuple':
            ret = {'identifier': ('tuple', node), 
                   'param': [], 
                   'slice': []
            }
        
        elif node_type == 'none':
            ret = {'identifier': ('None', node), 
                   'param': [], 
                   'slice': []
            }
        
        elif node_type == 'ellipsis':
            ret = {'identifier': ('ellipsis', node), 
                   'param': [], 
                   'slice': []
            }
        
        else:
            ret = {'identifier':(), 'param': [], 'slice': []}

            for child in node.children:  
                node_ret_dict = self._deal_primary_expression(child)
                if node_ret_dict['identifier'] and not ret['identifier']:
                    ret = node_ret_dict
                else:
                    if node_ret_dict['identifier']:
                        ret['param'] += [node_ret_dict['identifier']]
                    ret['param'] += node_ret_dict['param']
                    ret['slice'] += node_ret_dict['slice']
        
        return ret

    def appear_in_state(self, var_name, states):
        if var_name in ['int', 'bool', 'str', 'float', 'list', 'dict', 'set', 'tuple', 'self']:
            return []

        str_list = var_name.split('.')
        tmp = ''
        keys = states.keys()
        res = []
        for elem in str_list:
            tmp += elem
  
            if tmp in keys:
                res.append(tmp)
            tmp += '.'
        return res

    def create_import_node(self, root_node, var_name, states, module, name, add_flag=True):
        dfg_node = self.DFG.create_dfg_node(root_node, var_name, NodeType.IMPORT, module=module, name=name)

        if add_flag:
            if var_name in states.keys():
                states[var_name].append(dfg_node.index)
            else:
                states[var_name] = [dfg_node.index]
        
        return dfg_node


    def create_node(self, root_node, var_name, states, add_flag=True, check_flag=True):
        dfg_node = self.DFG.create_dfg_node(root_node, var_name, NodeType.VARIABLE)
        
        if check_flag:
            keys = self.appear_in_state(var_name, states)
            for key in keys:
                if key == 'self' and var_name.startswith('self.'):
                    continue
                for i in states[key]:
                    edge = (dfg_node.index, i)
                    if EdgeType.COMES_FROM in self.DFG.dfg_edges.keys():
                        self.DFG.dfg_edges[EdgeType.COMES_FROM].append(edge)
                    else:
                        self.DFG.dfg_edges[EdgeType.COMES_FROM] = [edge]

            if var_name.startswith('self.') and len(self.class_name) != 0:
                # link 'self.' to 'class_name' 
                class_name_index = self.class_name_node_mapping[self.class_name[-1]]
                self.DFG.dfg_edges[EdgeType.COMES_FROM].append((dfg_node.index, class_name_index))
                
                keys_in_map = self.appear_in_state(var_name, self.class_attri_map[self.class_name[-1]])
                for key in keys_in_map:
                    source_index = self.class_attri_map[self.class_name[-1]][key]
                    for k in source_index:
                        self.DFG.dfg_edges[EdgeType.COMES_FROM].append((dfg_node.index, k))
                
                if len(keys_in_map) == 0 and var_name not in states.keys() and var_name in self.class_methods.keys():
                    if var_name in self.not_linked_node.keys():
                        self.not_linked_node[var_name].append(dfg_node.index)
                    
                    else:
                        self.not_linked_node[var_name] = [dfg_node.index]
                    
            global_keys = self.appear_in_state(var_name, self.global_states)
            for g_key in global_keys:
                if self.global_states[g_key]:
                    self.DFG.dfg_edges[EdgeType.COMES_FROM].append((dfg_node.index, self.global_states[g_key]))  
        
        if add_flag:
            
            if var_name in states.keys():
                states[var_name].append(dfg_node.index)
            else:
                states[var_name] = [dfg_node.index]

            if root_node.id in self.global_var_name_ast_id:
                if var_name == self.class_name[-1]:
                    class_var_name = '.'.join(self.class_name)
                    
                else:
                    class_var_name = '.'.join(self.class_name) + '.' + var_name
                
                self.global_states[class_var_name] = dfg_node.index
                key_of_class_attri_map = 'self.' + var_name
                self.class_attri_map[self.class_name[-1]][key_of_class_attri_map] = [dfg_node.index]
                
        return dfg_node
   
if __name__ == '__main__':
    import sys
    fname = sys.argv[1]
    parser = PythonParser()
    parser.parse_file(fname)
    # G = parser.DFG.visualize(dot_file=sys.argv[2])