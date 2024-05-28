import os
import tree_sitter_python as tspython
from tree_sitter import Language, Parser


class astVisiter(object):
    def __init__(self):
        self.node_info = {}
        # source code
        self.source_code = None

        self.DOCSTRING_TYPES = {"comment", "string", "concatenated_string"}
    

    def clear(self):
        self.node_info = {}
        self.source_code = None

    
    def get_info(self):
        '''
        Return: {
            name: {
                "type": str,                         # type: "Module", "Class", "Function", "Variable"
                "def": str,
                "docstring": str (optional),
                "body": str (optional),
                "sline": int (optional),
                "in_class": str (optional),
                "in_init": bool (optional),
                "rels": [[name:str, type:str], ],    # type: "Assign", "Hint", "Rhint", "Inherit"
                "import": [module:str, name:str]     # "Import"
            }
        }
        '''
        return self.node_info
    
    
    def set_code(self, source_code):
        self.source_code = source_code


    def _get_code(self, start_pos, end_pos):
        return self.source_code[start_pos:end_pos].decode('utf-8', errors='ignore')


    def _save_import_info(self, stat, lineno, module, name=None, alias=None):
        # the imported name that actually works
        if alias is not None:
            variable = alias
        elif name is not None:
            variable = name
        else:
            variable = module
        
        assert variable is not None, f'Unexpected import statement: {stat}'

        self.node_info[variable] = {
            "type": "Variable",
            "def": stat,
            "sline": lineno,
            "import": [module, name]
        }
    

    def _get_docsting(self, node):
        '''
        First node in pre-order, which is a comment or a string
        '''
        p = node
        has_docsting = True
        while p.type not in self.DOCSTRING_TYPES:
            children = p.children
            if len(children) == 0:
                has_docsting = False
                break
            
            p = children[0]

        if has_docsting:
            return p.text.decode('utf-8', errors='ignore')
        
        return None


    def _get_all_attrs(self, node, save_set):
        '''
        Extract all identifier/attribute in node and its children
        '''
        node_type = node.type
        if node_type == 'identifier' or node_type == 'attribute':
            attr = self._get_primary_expression(node)
            if attr is not None:
                save_set.add(attr)
        else:
            for child in node.children:
                self._get_all_attrs(child, save_set)
    

    def _get_main_type(self, node, type_set, related_set):
        main_type = None

        node_type = node.type
        if node_type == 'subscript':
            '''
            subscript: $ => prec(PREC.call, seq(
                field('value', $.primary_expression),
                '[',
                commaSep1(field('subscript', choice($.expression, $.slice))),
                optional(','),
                ']'
            ))
            '''
            main_type = self._get_primary_expression(node.child_by_field_name('value'))
            for child in node.children_by_field_name('subscript'):
                self._get_all_attrs(child, related_set)
        
        elif node_type == 'identifier' or node_type == 'attribute':
            main_type = self._get_primary_expression(node)
        
        elif node_type == 'type' or 'binary_operator':
            for child in node.children:
                self._get_main_type(child, type_set, related_set)
        
        if main_type is not None:
            type_set.add(main_type)


    def _get_type_hints(self, node):
        '''
        type: $ => $.expression
        '''
        type_set = set()
        related_set = set()

        self._get_main_type(node, type_set, related_set)

        return type_set, related_set


    def _get_superclasses(self, node):
        '''
        argument_list: $ => seq(
            '(',
            optional(commaSep1(
                choice(
                $.expression,
                $.list_splat,
                $.dictionary_splat,
                alias($.parenthesized_list_splat, $.parenthesized_expression),
                $.keyword_argument
                )
            )),
            optional(','),
            ')'
        )
        '''
        ret = set()

        for child in node.children:
            child_type = child.type
            if child_type == 'identifier' or child_type == 'attribute':
                attr = self._get_primary_expression(child)
                if attr is not None:
                    ret.add(attr)
        
        return ret

    
    def _get_assignment_info(self, node, cls=None, in_init=False):
        '''
        defined variables; optional assign/hints rels
        '''
        # {name: value}
        variables = set()

        lineno = node.start_point[0]
        stat = node.text.decode('utf-8', errors='ignore')

        p = node
        while p and p.type == 'assignment':
            '''
            assignment: $ => seq(
                field('left', $._left_hand_side),
                choice(
                    seq('=', field('right', $._right_hand_side)),
                    seq(':', field('type', $.type)),
                    seq(':', field('type', $.type), '=', field('right', $._right_hand_side))
                )
            )
            '''
            left_node = p.child_by_field_name('left')
            left_variables = self._get_left_hand_side(left_node, in_init)

            if cls:
                left_variables = [f'{cls}.{x}' for x in left_variables]
            
            if len(left_variables) == 1:
                variables.update(left_variables)

            for var_name in left_variables:
                self.node_info[var_name] = {
                    "type": "Variable",
                    "def": stat,
                    "sline": lineno,
                }

                if cls:
                    self.node_info[var_name]["in_class"] = cls
                
                if in_init:
                    self.node_info[var_name]["in_init"] = True

            # hints
            type_node = p.child_by_field_name('type')
            if type_node is not None:
                type_set, related_set = self._get_type_hints(type_node)
                rels = [[x, "Hint"] for x in type_set]
                for x in related_set:
                    rels.append([x, "Rhint"])
                    
                for var_name in left_variables:
                    self.node_info[var_name]["rels"] = rels
            
            p = p.child_by_field_name('right')
        
        # Assign rels
        if len(variables) > 0:
            right_attr = None
            if p is not None:
                right_attr = self._get_primary_expression(p)
            
            if right_attr:
                for var_name in variables:
                    if "rels" in self.node_info[var_name]:
                        self.node_info[var_name]["rels"].append([right_attr, 'Assign'])
                    else:
                        self.node_info[var_name]["rels"] = [[right_attr, 'Assign']]
    

    def _get_function_info(self, node, decorated_info, cls=None):
        '''
        function_definition: $ => seq(
            optional('async'),
            'def',
            field('name', $.identifier),
            field('parameters', $.parameters),
            optional(
                seq(
                '->',
                field('return_type', $.type)
                )
            ),
            ':',
            field('body', $._suite)
        )
        '''
        lineno = node.start_point[0]
        func_name = node.child_by_field_name('name').text.decode()
        if cls:
            func_name = f'{cls}.{func_name}'

        colon_index = -1
        for i, child in enumerate(node.children):
            if child.type == ':':
                colon_index = i
        
        next_node = node.children[colon_index + 1]

        # def stat
        def_content = self._get_code(node.start_byte, next_node.start_byte)
        if decorated_info is not None:
            def_content = decorated_info + def_content

        # hints for return type
        type_node = node.child_by_field_name('return_type')
        rels = None
        if type_node is not None:
            type_set, related_set = self._get_type_hints(type_node)
            rels = [[x, "Hint"] for x in type_set]
            for x in related_set:
                rels.append([x, "Rhint"])
        
        # docsting and body
        docstring = self._get_docsting(next_node)
        # body_node = node.child_by_field_name('body')
        body_content = self._get_code(next_node.start_byte, node.end_byte)

        self.node_info[func_name] = {
            "type": "Function",
            "sline": lineno,
            "def": def_content,
            "body": body_content
        }

        if docstring:
            self.node_info[func_name]["docstring"] = docstring
        
        if cls is not None:
            self.node_info[func_name]["in_class"] = cls
        
        if rels:
            self.node_info[func_name]["rels"] = rels

        return func_name


    def _get_class_info(self, node, decorated_info, p_cls=None):
        '''
        class_definition: $ => seq(
            'class',
            field('name', $.identifier),
            field('superclasses', optional($.argument_list)),
            ':',
            field('body', $._suite)
        )
        '''
        lineno = node.start_point[0]
        cls_name = node.child_by_field_name('name').text.decode()
        if p_cls:
            cls_name = f'{p_cls}.{cls_name}'

        colon_index = -1
        for i, child in enumerate(node.children):
            if child.type == ':':
                colon_index = i
        next_node = node.children[colon_index + 1]
        
        rels = None
        superclass_node = node.child_by_field_name('superclasses')
        if superclass_node is not None:
            superclasses = self._get_superclasses(superclass_node)
            rels = [[x, 'Inherit'] for x in superclasses]

        # def stat
        def_content = self._get_code(node.start_byte, next_node.start_byte)
        if decorated_info is not None:
            def_content = decorated_info + def_content

        # docsting and body
        docstring = self._get_docsting(next_node)

        self.node_info[cls_name] = {
            "type": "Class",
            "sline": lineno,
            "def": def_content
        }

        if docstring:
            self.node_info[cls_name]["docstring"] = docstring
        
        if p_cls is not None:
            self.node_info[cls_name]["in_class"] = p_cls
        
        if rels:
            self.node_info[cls_name]["rels"] = rels

        # functions and variables in class
        child_decorated = None
        body_node = node.child_by_field_name('body')
        for item in body_node.children:
            if item.type == 'decorated_definition':
                def_item = item.child_by_field_name('definition')
                child_decorated = self._get_code(item.start_byte, def_item.start_byte)
                item = def_item
            
            item_type = item.type
            if item_type == 'expression_statement':
                for child in item.children:
                    if child and child.type == 'assignment':
                        self._get_assignment_info(child, cls_name)
            
            elif item_type == 'function_definition':
                func_name = self._get_function_info(item, child_decorated, cls_name)
                child_decorated = None

                if func_name == f'{cls_name}.__init__':
                    # defined variables in __init__()
                    for child_item in item.child_by_field_name('body').children:
                        if child_item.type == 'expression_statement':
                            for child in child_item.children:
                                if child and child.type == 'assignment':
                                    self._get_assignment_info(child, cls_name, True)

            elif item_type == 'class_definition':
                # inner class
                self._get_class_info(item, child_decorated, cls_name)
                child_decorated = None


    def visit_root(self, root):
        # Module is recorded as ""
        self.node_info[""] = {"type": "Module"}
        docstring = self._get_docsting(root)
        if docstring:
            self.node_info[""]["docstring"] = docstring

        # global info
        decorated_info = None
        for node in root.children:
            if node.type == 'decorated_definition':
                '''
                decorated_definition: $ => seq(
                    repeat1($.decorator),
                    field('definition', choice(
                        $.class_definition,
                        $.function_definition
                    ))
                )
                '''
                def_node = node.child_by_field_name('definition')
                decorated_info = self._get_code(node.start_byte, def_node.start_byte)
                node = def_node
            
            node_type = node.type
            # print(node_type)

            if node_type == 'future_import_statement':
                '''
                future_import_statement: $ => seq(
                    'from',
                    '__future__',
                    'import',
                    choice(
                        $._import_list,
                        seq('(', $._import_list, ')'),
                    )
                )
                '''
                stat = node.text.decode('utf-8', errors='ignore')
                lineno = node.start_point[0]

                children = node.children
                for i in range(3, len(children)):
                    name, alias = self._get_import_list(children[i])
                    if name is not None:
                        self._save_import_info(stat, lineno, "__future__", name, alias)

            elif node_type == 'import_statement':
                '''
                import_statement: $ => seq(
                    'import',
                    $._import_list
                )
                '''
                stat = node.text.decode('utf-8', errors='ignore')
                lineno = node.start_point[0]

                children = node.children
                for i in range(1, len(children)):
                    name, alias = self._get_import_list(children[i])
                    if name is not None:
                        self._save_import_info(stat, lineno, name, None, alias)

            elif node_type == 'import_from_statement':
                '''
                import_from_statement: $ => seq(
                    'from',
                    field('module_name', choice(
                        $.relative_import,
                        $.dotted_name
                    )),
                    'import',
                    choice(
                        $.wildcard_import,
                        $._import_list,
                        seq('(', $._import_list, ')')
                    )
                )
                '''
                stat = node.text.decode('utf-8', errors='ignore')
                lineno = node.start_point[0]

                module = node.child_by_field_name('module_name').text.decode()

                children = node.children
                for i in range(3, len(children)):
                    child = children[i]
                    # TODO handle wildcard_import in future
                    if child.type != 'wildcard_import':
                        name, alias = self._get_import_list(child)
                        if name is not None:
                            self._save_import_info(stat, lineno, module, name, alias)
            
            elif node_type == 'expression_statement':
                for child in node.children:
                    if child and child.type == 'assignment':
                        self._get_assignment_info(child)
            
            elif node_type == 'function_definition':
                self._get_function_info(node, decorated_info)
                decorated_info = None

            elif node_type == 'class_definition':
                self._get_class_info(node, decorated_info)
                decorated_info = None
        

    def _get_import_list(self, node):
        '''
        _import_list: $ => seq(
            commaSep1(field('name', choice(
                $.dotted_name,
                $.aliased_import
            ))),
            optional(',')
        )
        '''
        name = alias = None

        if node.type == 'dotted_name':
            name = node.text.decode()
        
        elif node.type == 'aliased_import':
            '''
            aliased_import: $ => seq(
                field('name', $.dotted_name),
                'as',
                field('alias', $.identifier)
            )
            '''
            name = node.child_by_field_name('name').text.decode()
            alias = node.child_by_field_name('alias').text.decode()

        return name, alias
    

    def _judge_variable(self, node, in_init):
        if not in_init:
            if node.type == 'identifier':
                return node.text.decode()
        else:
            # self.identifier in __init__()
            if node.type == 'attribute' and node.child_by_field_name('object').text.decode() == 'self':
                attr_node = node.child_by_field_name('attribute')
                if attr_node.type == 'identifier':
                    return attr_node.text.decode()

        return None
    

    def _get_left_hand_side(self, node, in_init=False):
        '''
        Get all attributes
        '''
        ret = set()
        if node.type == 'pattern_list':
            for item in node.children:
                if item.type != ',':
                    name = self._judge_variable(item, in_init)
                    if name:
                        ret.add(name)
        else:
            name = self._judge_variable(node, in_init)
            if name:
                ret.add(name)

        return ret


    def _get_primary_expression(self, node):
        # identifier, attribute, call
        node_type = node.type
        if node_type == 'identifier':
            return node.text.decode()

        elif node_type == 'attribute':
            '''
            attribute: $ => prec(PREC.call, seq(
                field('object', $.primary_expression),
                '.',
                field('attribute', $.identifier)
            ))
            '''
            object_node = node.child_by_field_name('object')
            attr = node.child_by_field_name('attribute').text.decode()

            prefix_name = self._get_primary_expression(object_node)
            if prefix_name is not None:
                attribute = '{}.{}'.format(prefix_name, attr)
                return attribute

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
            function_name = self._get_primary_expression(function_node)
            if function_name is not None:
                return function_name
        
        elif node_type == 'string' or node_type == 'concatenated_string':
            return 'str'
        
        elif node_type == 'integer':
            return 'int'
        
        elif node_type == 'float':
            return 'float'
        
        elif node_type == 'true' or node_type == 'false':
            return 'bool'
        
        elif node_type == 'list' or node_type == 'list_comprehension':
            return 'list'
        
        elif node_type == 'dictionary' or node_type == 'dictionary_comprehension':
            return 'dict'
        
        elif node_type == 'set' or node_type == 'set_comprehension':
            return 'set'
        
        elif node_type == 'tuple':
            return 'tuple'

        return None


class PythonParser(object):
    def __init__(self):
        PY_LANGUAGE = Language(tspython.language())
        self.parser = Parser(PY_LANGUAGE)

        self.visiter = astVisiter()
    

    def parse(self, py_file):

        with open(py_file, 'rb') as f:
            source_code = f.read()
        
        tree = self.parser.parse(source_code)
        
        self.visiter.clear()
        self.visiter.set_code(source_code)
        self.visiter.visit_root(tree.root_node)

        return self.visiter.get_info()