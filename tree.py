import os
import re
import sys

from clingo.application import clingo_main, Application
from clingo.propagator import Propagator

from ollama import chat

TRIES = 5

class SumPropagator(Propagator):
    def __init__(self, model):
        # Matrix for the entered letters
        self.grid = [["_"] * 5 for _ in range(5)]


        # 3-dimensional dictionarsy for the solver literals
        self.atom_lit = {}
        for i in range(5):
            self.atom_lit[i] = {}
            for j in range(5):
                self.atom_lit[i][j] = {}

        # Collects what rows and cols have been checked as tuples
        self.done = set()

        self.row = [""]*5
        self.col = [""]*5

        # collects all literals which need to be made true successively
        self.to_true = []

        self._model = model

    def init(self, init):
        for i in init.symbolic_atoms:
            sym = i.symbol
            if sym.name == "answer":
                args = sym.arguments
                self.atom_lit[args[0].number][args[1].number][args[2].name] = init.solver_literal(i.literal)

            if sym.name == "row":
                args = sym.arguments
                self.row[args[0].number] = str(args[1].string)

            if sym.name == "col":
                args = sym.arguments
                self.col[args[0].number] = args[1].string

    def _print_grid(self):
        prompt = ""
        for i in self.grid:
            for j in i:
                prompt += f"{j} "
            prompt += "\n"
        return prompt

    def _get_thoughts(self):
        with open("prompts/propose.txt", "r") as file:
            template = file.read()

        # Add prompts
        state = ""
        for i,r in enumerate(self.row):
            situation = "".join(self.grid[i])
            state += f"h{i}. {r}, state={situation}\n"
        for i,c in enumerate(self.col):
            situation = "".join([row[i] for row in self.grid])
            state += f"v{i}. {c}, state={situation}\n"

        state += "\n"
        state += self._print_grid()

        prompt = template.replace("{input}", state)
        # print(prompt)
        print(self._print_grid())

        response = chat(model=self._model, messages=[
            {
                "role" : "user",
                "content" : prompt,
            }
        ], options={"num_predict":400})

        # Regular expression pattern
        # print(response["message"]["content"])
        pattern = r"[hv]\d\S\s\w{5}\s\((?:certain|high|medium|low)\)"
        choices = re.findall(pattern, response["message"]["content"])

        ranking_order = {"certain": 0, "high": 1, "medium": 2, "low": 3}
        tuples_list = []
        for c in choices:
            parts = c.split(" ")
            place = parts[0][0:-1]
            word = parts[1]
            ranking = parts[2][1:-1]
            t = (place, word, ranking)
            tuples_list.append(t)

        tuples_list = sorted(tuples_list, key=lambda x: ranking_order[x[2]])

        return(tuples_list)


    def decide(self, thread_id, assignment, fallback):

        if self.to_true == []:
            choices = []
            safeguard = 0
            while True:
                while not choices:
                    choices += self._get_thoughts()
                    safeguard += 1
                    print(choices)

                choice = choices.pop(0)

                if not choice[0] in self.done:
                    i = int(choice[0][-1])
                    break

                if safeguard >= TRIES:
                    os._exit(1)
            print(choice)

            self.done.add(choice[0])

            for j,l in enumerate(choice[1]):
                if "h" in choice[0]:
                    lit = self.atom_lit[i][j][l]
                    if assignment.is_free(lit):
                        self.to_true.append(lit)
                        self.grid[i][j] = l
                else:
                    lit = self.atom_lit[j][i][l]
                    if assignment.is_free(lit):
                        self.to_true.append(lit)
                        self.grid[j][i] = l

        if not self.to_true:
            return self.decide(thread_id, assignment, fallback)
        else:
            return self.to_true.pop()


class MiniClingconApp(Application):
    program_name = "tree"
    version = "1.0"

    def __init__(self):
        self._model = "mistral-small"

    def _parse_model(self, option):
        self._model = str(option)
        return True

    def register_options(self, options):
        group = 'Solving Exercises Options'
        options.add(group, 'model', 'Model used for generating search options', self._parse_model, argument="<str>")

    def main(self, control, files):
        control.register_propagator(SumPropagator(self._model))
        control.load("base.lp")

        for path in files:
            control.load(path)
        if not files:
            control.load("-")
        control.ground([("base", [])])
        control.solve()

if __name__ == "__main__":
    clingo_main(MiniClingconApp(), sys.argv[1:])
