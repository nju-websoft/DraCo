import re
import argparse
from fuzzywuzzy import fuzz
import json
import keyword
from functools import lru_cache
from nltk.tokenize import RegexpTokenizer


IDENTIFIER_REGEX = re.compile('[_a-zA-Z][_a-zA-Z0-9]*')
string_pattern = r'"([^"\\]*(\\.[^"\\]*)*)"|\'([^\'\\]*(\\.[^\'\\]*)*)\''
code_tokenizer = RegexpTokenizer(r'\w+')


@lru_cache()
def get_language_keywords():
    return frozenset(k for k in keyword.kwlist if k != 'True' and k != 'False')


def is_identifier(token):
    return True if IDENTIFIER_REGEX.match(token) \
                   and token not in get_language_keywords() \
        else False


def remove_comments(code):
    code = re.sub(r'#.*', '', code)
    return code


def extract_identifiers(source_code):
    # the main idea is to remove String from a source code
    # then, tokenize the code to get all words and match with identifier regular expression
    # check if it is a language specific keyword, it not, then it is an identifier
    source_code_without_strings = re.sub(string_pattern, '', source_code)
    _ids = [t for t in code_tokenizer.tokenize(source_code_without_strings) if is_identifier(t)]
    return _ids


def compute_id_match(pred_ids, target_ids):
    em = int(pred_ids == target_ids)

    pred_ids = list(set(pred_ids))
    target_ids = list(set(target_ids))
    tp = 0
    fp = 0
    fn = 0
    for pid in pred_ids:
        if pid in target_ids:
            tp += 1
        else:
            fp += 1
    for tid in target_ids:
        if tid not in pred_ids:
            fn += 1
    
    precision = tp / (tp + fp) if (tp + fp) != 0 else 0
    recall = tp / (tp + fn) if (tp + fn) != 0 else 0
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) != 0 else 0

    return em, precision, recall, f1


def main():
    parser = argparse.ArgumentParser(description='Evaluate predictions for code completion (line level).')
    parser.add_argument('--path', required=True, help="filename of predictions in json format.")
    args = parser.parse_args()

    fpath = args.path
    
    with open(fpath, 'r') as load_f:
        load_dict = json.load(load_f)

    total = len(load_dict)
    
    EM = 0.0
    edit_sim = 0.0
    em_list = []
    p_list = []
    r_list = []
    f1_list = []
    for elem in load_dict:
        pred = elem['pred']
        gt = elem['gt']

        # 1 - distance / (len(pred) + len(gt)): Levenshtein distance with a substitution weight of 2
        edit_sim += fuzz.ratio(pred, gt)
        if pred.split() == gt.split():
            EM += 1
        
        # comments matter for identifier match
        pred_ids = extract_identifiers(remove_comments(pred))
        target_ids = extract_identifiers(remove_comments(gt))

        em, precision, recall, f1 = compute_id_match(pred_ids, target_ids)
        em_list.append(em)
        p_list.append(precision)
        r_list.append(recall)
        f1_list.append(f1)

    print(f'Num of test data: {total}')
    print(f'# Code Match')
    print(f'EM: {round(EM/total*100, 2)}')
    print(f'ES: {round(edit_sim/total, 2)}')
    print(f'# Identifier Match')
    print(f'ID.EM: {round(sum(em_list)/total*100, 2)}')
    print(f'F1: {round(sum(f1_list)/total*100, 2)}')
    # print(f'Precision: {round(sum(p_list)/total*100, 2)}')
    # print(f'Recall: {round(sum(r_list)/total*100, 2)}')


if __name__ == "__main__":
    main()