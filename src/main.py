import os
import json
from generator import Generator as promptGenerator
from utils import DS_REPO_DIR, DS_FILE, DS_GRAPH_DIR
from argparse import ArgumentParser


if __name__ == '__main__':

    parser = ArgumentParser()
    parser.add_argument('-m', '--model', required=True, help='Code LMs, incl. codegen, codegen25, santacoder, starcoder, codellama, gpt35, gpt4')
    parser.add_argument('-f', '--file', required=True, help='prompt file')
    args = parser.parse_args()

    generator = promptGenerator(DS_REPO_DIR, DS_GRAPH_DIR, args.model.lower())

    with open(DS_FILE, 'r') as f:
        dataset = [json.loads(line) for line in f.readlines()]
    print(f'There are {len(dataset)} samples in ReccEval.')
    
    ret = []
    for i, item in enumerate(dataset):
        fpath = os.path.join(DS_REPO_DIR, item['fpath'])
        try:
            prompt = generator.retrieve_prompt(item['pkg'], fpath, item['input'])
        except Exception as e:
            print(i, item['fpath'])
            print(repr(e))
            exit(0)
        else:
            ret.append(prompt)

    print(f'Generate prompts for {len(ret)} samples.')
    with open(args.file, 'w') as f:
        for item in ret:
            json.dump(item, f)
            f.write('\n')