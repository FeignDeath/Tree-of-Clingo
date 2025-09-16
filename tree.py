import enum
import itertools
import os
import re
import sys

from clingo.application import Flag, clingo_main, Application
from clingo.propagator import Assignment, Propagator, PropagatorCheckMode
from clingo.symbol import Function

from ollama import chat

VERBOSE = 1
SAMPLING = 2
BREADTH = 5

class SumPropagator(Propagator):
    def __init__(self, model, check_answers):
        # 3-dimensional dictionary for the solver literals
        self.atom_lit = {}
        for i in range(5):
            self.atom_lit[i] = {}
            for j in range(5):
                self.atom_lit[i][j] = {}

        self.lit_thought = {}

        self.row = [""]*5
        self.col = [""]*5

        self.ranking_order = {"certain": 0, "high": 1, "medium": 2, "low": 3}

        self._model = model
        self._check_answers = check_answers

    def thought_structure(self, control, changes = []):
        # This creates the corresponding structure for the thoughts for the propagator to use
        lits = []
        for t in self._get_thoughts(control.assignment):
            lit = control.add_literal()
            control.add_watch(lit)
            lits.append(lit)
            self.lit_thought[lit] = t
            if VERBOSE > 0: print("",lit,t)

            # Add nogoods to make sure every word enforces the correct letter positions
            for i,w in enumerate(t[1]):
                if "h" in t[0]:
                    letterlit = self.atom_lit[int(t[0][-1])][i][w]
                else:
                    letterlit = self.atom_lit[i][int(t[0][-1])][w]

                control.add_clause([-lit,letterlit])

        # One of those literals must hold if the previous holds
        control.add_clause(lits+list(map(lambda x: -x, changes)))

        # Make sure only one is picked by adding all pairs as nogoods
        for pair in itertools.combinations(list(map(lambda x: -x,lits)),2):
            control.add_clause(list(pair))

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

        init.check_mode = PropagatorCheckMode.Fixpoint

        # Create literals for the thoughts of the LLM, they are then used in decide to guide the search
        if VERBOSE > 0: print("Initial Thoughts:")
        self.thought_structure(init)

    def _get_grid(self, assignment):
        grid = [["_"]*5]*5
        for i in self.atom_lit:
            for j in self.atom_lit[i]:
                for l in self.atom_lit[i][j]:
                    if assignment.is_true(self.atom_lit[i][j][l]):
                        grid[i][j] = l
        return grid

    def _print_grid(self, assignment):
        grid = ""
        for i in self.atom_lit:
            for j in self.atom_lit[i]:
                to_print = "_"
                for l in self.atom_lit[i][j]:
                    if assignment.is_true(self.atom_lit[i][j][l]):
                        to_print = l
                grid += f"{to_print} "
            grid += "\n"
        return grid

    def _get_thoughts(self, assignment):
        with open("prompts/propose.txt", "r") as file:
            template = file.read()

        # Generate Input
        state = ""
        # Place, hint and situation for rows
        for i,r in enumerate(self.row):
            situation = "".join(self._get_grid(assignment)[i])
            state += f"h{i}. {r}, state={situation}\n"
        # Place, hint and situation for cols
        for i,c in enumerate(self.col):
            situation = "".join([row[i] for row in self._get_grid(assignment)])
            state += f"v{i}. {c}, state={situation}\n"

        # Add the current grid (probably as useless as the situation)
        state += "\n"
        state += self._print_grid(assignment)

        # Add the input to the template for the finished prompt
        prompt = template.replace("{input}", state)

        output = ""
        for i in range(SAMPLING):
            response = chat(model=self._model, messages=[
                {
                    "role" : "user",
                    "content" : prompt,
                }
            ], options={"num_predict":400})
            output += response["message"]["content"]

        # Regular expression pattern to find all expresions of the for "h1 words high"
        pattern = r"[hv][0-4]\S\s\w{5}\s\((?:certain|high|medium|low)\)"
        choices = re.findall(pattern, output)

        # Transform the strings into proper tuples
        tuples_list = set()
        for c in choices:
            parts = c.split(" ")
            place = parts[0][0:-1]
            word = parts[1].lower()
            ranking = parts[2][1:-1]
            t = (place, word, ranking)

            # Check whether all is possible with the current assignement
            possible = True
            for i,w in enumerate(word):
                if "h" in place:
                    lit = self.atom_lit[int(place[-1])][i][w]
                    if assignment.is_false(lit):
                        possible = False
                if "v" in place:
                    lit = self.atom_lit[i][int(place[-1])][w]
                    if assignment.is_false(lit):
                        possible = False

            # Only append things which are possible
            if possible and not any(t[0:2] == value[0:2] for value in self.lit_thought.values()):
                tuples_list.add(t)

        # Sort them by their assigned probability
        tuples_list = sorted(tuples_list, key=lambda x: self.ranking_order[x[2]])

        if len(tuples_list) > BREADTH:
            return tuples_list[0:5]
        else:
            return(tuples_list)

    def decide(self, thread_id, assignment, fallback):
        if VERBOSE > 0: print("DECIDE:")
        choosen = min(
            (lit for lit in self.lit_thought if assignment.is_free(lit)),
            key=lambda lit: self.ranking_order[self.lit_thought[lit][2]],
            default=None)

        if choosen:
            if VERBOSE > 0: print(choosen, self.lit_thought[choosen])
            return choosen
        else:
            os._exit(1)

    def propagate(self, control, changes):
        # manage overwriting
        thought = self.lit_thought[changes[0]]


        # Interrupt Propagation if at least one letter holds true for every field
        if all(all(any(control.assignment.is_true(i) for i in e.values()) for e in d.values()) for d in self.atom_lit.values()):
            if VERBOSE > 0: print("Done")
            # Set all other assignables to False
            for row in self.atom_lit.values():
                for col in row.values():
                    for lit in col.values():
                        if control.assignment.is_free(lit):
                            control.add_nogood([lit])
            control.propagate()

            return

        print(self._print_grid(control.assignment))
        if VERBOSE > 0: print("PROPAGATE:")
        if VERBOSE > 1: print(" Previous", changes)
        thoughts = self._get_thoughts(control.assignment)

        # If not done, check whether current state is possible
        if self._check_answers:
            if VERBOSE > 0: print(" LLM Checking State")
            with open("prompts/propose.txt", "r") as file:
                template = file.read()

            found_impossible = False
            for i,r in enumerate(self.row):
                question = r + ": " + "".join(self._get_grid(control.assignment)[i])
                prompt = template.replace("{input}", question)
                response = chat(model=self._model, messages=[
                    {
                        "role" : "user",
                        "content" : prompt,
                    }
                ], options={"num_predict":400})
                if "impossible" in response["message"]["content"].lower():
                    found_impossible = True
                    break

            for i,r in enumerate(self.col):
                if found_impossible:
                    break
                question = r + ": " + "".join([row[i] for row in self._get_grid(control.assignment)])
                prompt = template.replace("{input}", question)
                response = chat(model=self._model, messages=[
                    {
                        "role" : "user",
                        "content" : prompt,
                    }
                ], options={"num_predict":400})
                if "impossible" in response["message"]["content"].lower():
                    found_impossible = True

            if found_impossible:
                if VERBOSE > 0: print(" Impossible")
                control.add_nogood([lit for lit in self.lit_thought if control.assignment.is_true(lit)])
                return

        # If there are no more thoughts to pick, the current state is illegal
        if not thoughts:
            if VERBOSE > 0: print("No more thoughts.")
            control.add_nogood([lit for lit in self.lit_thought if control.assignment.is_true(lit)])

        # Create literals for the thoughts of the LLM, they are then used in decide to guide the search
        else:
            self.thought_structure(control,changes)

        control.propagate()

    def check(self, control):
        # Interrupt checking if at least one letter holds true for every field
        if all(all(any(control.assignment.is_true(i) for i in e.values()) for e in d.values()) for d in self.atom_lit.values()):
            if VERBOSE > 0: print("Done")
            return

        if VERBOSE > 0: print("CHECK")
        if not any(control.assignment.is_free(lit) for lit in self.lit_thought):
            if VERBOSE > 1: print(" No thoughts!")
            control.add_nogood([lit for lit in self.lit_thought if control.assignment.is_true(lit)])

    def undo(self, thread_id, assignment, changes):
        if VERBOSE > 0:
            print("UNDO:")
            print(changes)
        for c in changes:
            if c in self.lit_thought:
                del self.lit_thought[c]

class MiniClingconApp(Application):
    program_name = "tree"
    version = "1.0"

    def __init__(self):
        self._model = "mistral-small"
        self._duplicates = Flag()
        self._check_answers = Flag()

    def _parse_model(self, option):
        self._model = str(option)
        return True

    def register_options(self, options):
        group = 'Tree Search Options'
        options.add(group, 'model', 'Model used for generating search options', self._parse_model, argument="<str>")
        options.add_flag(group, 'duplicates', "Allows duplicate letters", self._duplicates)
        options.add_flag(group, 'check-answers', "Let the LLM check the possibility of answers", self._check_answers)

    def main(self, control, files):
        control.register_propagator(SumPropagator(self._model, self._check_answers.flag))
        control.load("base.lp")

        for path in files:
            control.load(path)
        if not files:
            control.load("-")
        control.ground([("base", [])])
        control.assign_external(Function("duplicates"),self._duplicates.flag)
        control.solve()

if __name__ == "__main__":
    clingo_main(MiniClingconApp(), sys.argv[1:])
