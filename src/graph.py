import heapq


TRANS_RELS = {'assign', 'as', 'comesfrom', 'type', 'successor'}

class tGraph(object):
    def __init__(self, df_graph=None):
        if df_graph:
            self._trans_tables(df_graph)
        else:
            self.node_dict = {}
            self.in_table = {}
            self.out_table = {}
        
        self.module_info = {}
    

    def _clean_state(self):
        self.visit_dict = {}
        self.step_dict = {}

    
    def _trans_tables(self, df_graph):
        '''
        adjacency list
        '''
        self.node_dict = df_graph.dfg_nodes
        self.in_table = {}
        self.out_table = {}

        for item in self.node_dict:
            self.in_table[item] = []
            self.out_table[item] = []

        for key, value in df_graph.dfg_edges.items():
            for item in value:
                self.in_table[item[0]].append((item[1], key))
                self.out_table[item[1]].append((item[0], key))
    
    def get_last_k_lines(self, last_k=1):
        '''
        variables in (last_line + 1 - last_k ~ last_line)
        '''

        linenos = set([x.ast_node.start_point[0] for x in self.node_dict.values()])
        last_lines = heapq.nlargest(last_k, linenos)

        variables = [k for k,v in self.node_dict.items() if v.ast_node.start_point[0] in last_lines]
        variables.sort(key=lambda x:self.node_dict[x].ast_node.start_point)

        return variables


    def get_linenos(self, node_list):
        return sorted(set([self.node_dict[x].ast_node.start_point[0] for x in node_list]), reverse=True)
    

    def DFS_table(self, node, hop, limit_assign=False, reverse=False, end_nodes=None):
        if node not in self.step_dict:
            self.step_dict[node] = hop
        else:
            self.step_dict[node] = min(self.step_dict[node], hop)

        if node not in self.node_dict or node in self.visit_dict:
            return
        
        if end_nodes is not None and node in end_nodes:
            # is end node
            self.visit_dict[node] = True
            return
        
        if end_nodes is None:
            self.visit_dict[node] = True
        else:
            self.visit_dict[node] = False

        if reverse:
            for x, edge_type in self.in_table[node]:
                if not limit_assign or edge_type in TRANS_RELS:
                    self.DFS_table(x, hop+1, limit_assign, reverse, end_nodes)
                    if self.visit_dict[x]:
                        self.visit_dict[node] = True
        
        else:
            for x, edge_type in self.out_table[node]:
                if not limit_assign or edge_type in TRANS_RELS:
                    self.DFS_table(x, hop+1, limit_assign, reverse, end_nodes)
                    if self.visit_dict[x]:
                        self.visit_dict[node] = True

    
    def get_related_nodes(self, start_nodes, limit_assign=False, reverse=False, end_nodes=None):
        '''
        DFS via adjacency list
        start_nodes: cross-file nodes or variables in last line
        limit_assign: True / False
        reverse: True when start_nodes are variables, False when start_nodes are cross-file nodes
        end_nodes: only contains the nodes in the path to end_nodes

        Return: {id: hop}
        '''
        self._clean_state()
        for node in start_nodes:
            self.DFS_table(node, 0, limit_assign, reverse, end_nodes)
        
        return {k: self.step_dict[k] for k, v in self.visit_dict.items() if v}
    

    def trans_spec_rels(self, head, tail, rel_type):
        # update module info
        name = ''
        if rel_type == 'comesfrom':
            head_name = self.node_dict[head].var_name
            tail_name = self.node_dict[tail].var_name

            begin_index = tail_name.find(head_name+'.')
            if begin_index >= 0:
                name = tail_name[begin_index+len(head_name):]
        
        if tail not in self.module_info:
            self.module_info[tail] = set()

        for item in self.module_info[head]:
            if item[1] is None:
                self.module_info[tail].add((item[0], name.lstrip('.'), item[2]))
            else:
                self.module_info[tail].add((item[0], item[1]+name, item[2]))
    

    def get_subgraph(self, related_nodes):
        subgraph = tGraph()

        for x in related_nodes:
            subgraph.node_dict[x] = self.node_dict[x]
            subgraph.in_table[x] = []
            subgraph.out_table[x] = []
        
        for x in related_nodes:
            for y in self.out_table[x]:
                if y[0] in related_nodes:
                    subgraph.in_table[y[0]].append((x, y[1]))
                    subgraph.out_table[x].append(y)
        
        subgraph.module_info = {k:v for k,v in self.module_info.items() if k in related_nodes}
        
        return subgraph

    def dfs4trans(self, node, visit_set):
        if node in visit_set:
            return

        visit_set.add(node)

        for item in self.out_table[node]:
            if item[1] in TRANS_RELS:
                self.trans_spec_rels(node, item[0], item[1])
                self.dfs4trans(item[0], visit_set)
    

    def get_assign_subgraph(self, related_nodes, import_nodes):
        # subgraph with cross-file nodes
        subgraph = self.get_subgraph(related_nodes)
        subgraph.module_info = {x: {(subgraph.node_dict[x].module, subgraph.node_dict[x].name, subgraph.node_dict[x].ast_node.start_point[0])} for x in import_nodes}

        # DFS via TRANS_RELS
        for node in import_nodes:
            subgraph.dfs4trans(node, set())
        
        return subgraph


    def toposort_nodes(self):
        in_table = {k: [x[0] for x in v] for k, v in self.in_table.items()}
        out_table = {k: [x[0] for x in v] for k, v in self.out_table.items()}

        sort_list = []
        while len(out_table) > 0:
            item = None
            for k, v in out_table.items():
                if len(v) == 0:
                    item = k
                    break
            
            assert item is not None

            sort_list.append(item)

            for x in out_table.pop(item):
                in_table[x].remove(item)
            
            for x in in_table.pop(item):
                out_table[x].remove(item)
        
        return sort_list