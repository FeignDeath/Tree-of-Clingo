# Tree-of-Clingo

This project tried to replicate the tree of thought paper via Clingo propagator.

This is mostly a graveyard of attempts, but if you want to take a look at the working you run the main program in an environment with Clingo and Ollama setup, via:
```
python tree.py <instance> --model <model> --check --duplicates
```
- <instance> must be a problem instance in an .lp format, working instances can be found in data/instances/
- <model> must be an installed models served by Ollama 
- check activates the checking of the current state after every decision by the LLM vor viability
- duplicates allows duplicate letter and thus overwriting of previous words in the search process

An example command could look like:
```
python tree.py data/instances/ins_000.lp --model mistral-small --check
```
