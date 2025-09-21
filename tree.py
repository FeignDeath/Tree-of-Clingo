import copy
import itertools
import os
import re
import sys

from clingo.application import Flag, clingo_main, Application
from clingo.propagator import Propagator, PropagatorCheckMode
from clingo.symbol import Function
from prompts import propose
from prompts import evaluate

from ollama import chat

VERBOSE = 3
SAMPLING = 2
BREADTH = 100

class Grid():
    def __init__(self):
        """
        Initializes the grid object, which tracks the current_grid and saves previous states for backtracking.
        """

        self.current_grid = [["_"]*5 for _ in range(5)]
        self.states = {0:copy.deepcopy(self.current_grid)}
        self.current = 0

    def add(self, id:str, word:str):
        """
        Adds a new word to the grid.

        Parameters
        ----------
        id : str
            The position of the word. e.g. h0 for the first horizontal word.
        word : str
            The word to be entered.
        """

        for i,w in enumerate(word):
            if "h" in id:
                self.current_grid[int(id[-1])][i] = w
            else:
                self.current_grid[i][int(id[-1])] = w

        self.current += 1
        self.states[self.current] = copy.deepcopy(self.current_grid)
        return True

    def back(self):
        """
        Reverts to the previous state.
        """
        if self.current == 0:
            return False

        self.states.pop(self.current)
        self.current -= 1
        self.current_grid = copy.deepcopy(self.states[self.current])
        return True

    def get(self):
        """
        Returns the grid as a list of lists.

        Returns
        -------
        output : list[list[str]]
        """

        return self.current_grid

    def get_str(self):
        """
        Returns the grid as string with linebreaks for printing.

        Returns
        -------
        output : str
        """

        output = ""
        for i in self.current_grid:
            for j in i:
                output += f"{j} "
            output += "\n"
        return output

class LocalLLM():
    def __init__(self, model, limit = 500):
        self.model = model
        self.limit = limit

    def _message(self, message, history = []):
        response = chat(model=self.model, messages=history+[message], options={"num_predict":self.limit})
        # Removing the * is necessary due to the LLMs always wanting to answer markdown
        return response["message"]["content"].replace("*","")

    def think(self, input):
        message = propose.message
        message["content"] = message["content"].replace("{input}",input)
        return self._message(message,propose.history)

    def question(self, input):
        message = evaluate.message
        message["content"] = message["content"].replace("{input}",input)
        return self._message(message,evaluate.history)

class SumPropagator(Propagator):
    def __init__(self, model, check_answers):
        # 3-dimensional dictionary for the solver literals
        self.atom_lit = {}
        for i in range(5):
            self.atom_lit[i] = {}
            for j in range(5):
                self.atom_lit[i][j] = {}

        # To store what literals correspond to which thoughts.
        self.lit_thought = {}

        # Store initial hints
        self.row = [""]*5
        self.col = [""]*5

        # Define an order for sorting thoughts
        self.ranking_order = {"certain": 0, "high": 1, "medium": 2, "low": 3}

        # Stores seting whether answers are checked
        self._check_answers = check_answers

        # Tracks the state of the grid with the ability to add a new on top and to backtrack
        self.grid = Grid()

        # Initialize the LLM wrapper for easier calling
        self.llm = LocalLLM(model)

        # Used to supress some outputs when the run is done.
        self.done = False

    def _get_thoughts(self, assignment):
        # Generate Input
        state = ""
        # Place, hint and situation for rows
        for i,r in enumerate(self.row):
            situation = "".join(self.grid.get()[i])
            state += f"h{i}. {r}, state={situation}\n"
        # Place, hint and situation for cols
        for i,c in enumerate(self.col):
            situation = "".join([row[i] for row in self.grid.get()])
            state += f"v{i}. {c}, state={situation}\n"
        
        state += "\n" + self.grid.get_str()
        if VERBOSE > 2: print(" Situation:", state)

        output = ""
        for _ in range(SAMPLING):
            output += self.llm.think(state)
        if VERBOSE > 2: print(" Thoughts:", output)

        # Regular expression pattern to find all expresions of the for "h1 words high"
        pattern1 = r"[hv][0-4]\S\s\w{5}\s\((?:certain|high|medium|low)\)"
        choices1 = re.findall(pattern1, output)

        pattern21 = r"[hv][0-4]\S.*?\n- \w{5}\s\((?:certain|high|medium|low)\)"
        choices2 = re.findall(pattern21, output)
        pattern22 = r"[hv][0-4]\S.*?\n.*?\n- \w{5}\s\((?:certain|high|medium|low)\)"
        choices2 += re.findall(pattern22, output)

        possible_list = set()
        for c in choices2:
            place = c.split("\n")[0][0:2]
            word = c.split("\n")[-1].split(" ")[-2].lower()
            ranking = c.split("\n")[-1].split(" ")[-1][1:-1]
            possible_list.add((place,word,ranking))

        # Transform the strings into proper tuples
        for c in choices1:
            parts = c.split(" ")
            place = parts[0][0:-1]
            word = parts[1].lower()
            ranking = parts[2][1:-1]
            possible_list.add((place, word, ranking))

        tuples_list = set()
        for candidate in possible_list:
            place = candidate[0]
            word = candidate[1]
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

            # Filter out position where a word already holds
            if any((candidate[0:1] == self.lit_thought[lit][0:1] and assignment.is_true(lit)) for lit in self.lit_thought):
                possible = False

            # Filter out positions and words if they previously occured and it is still possible
            if any((candidate[0:2] == self.lit_thought[lit][0:2] and assignment.is_free(lit)) for lit in self.lit_thought):
                possible = False

            # Only append things which are possible
            if possible:
            # if possible:
                tuples_list.add(candidate)

        # Sort them by their assigned probability
        tuples_list = sorted(tuples_list, key=lambda x: self.ranking_order[x[2]])

        if len(tuples_list) > BREADTH:
            return tuples_list[0:BREADTH]
        else:
            return tuples_list

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
        # Deactivating this should lead to general thought pooling
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

    def decide(self, thread_id, assignment, fallback):
        choosen = min(
            (lit for lit in self.lit_thought if assignment.is_free(lit)),
            key=lambda lit: self.ranking_order[self.lit_thought[lit][2]],
            default=None)

        if choosen:
            if VERBOSE > 0: print("DECIDE:")
            if VERBOSE > 0: print(choosen, self.lit_thought[choosen])
            return choosen
        else:
            # Set everything else to false
            return -abs(fallback)

    def propagate(self, control, changes):
        # manage overwriting
        for c in changes:
            thought = self.lit_thought[c]
            self.grid.add(thought[0],thought[1])

        # Interrupt Propagation if at least one letter holds true for every field
        if all(all(any(control.assignment.is_true(i) for i in e.values()) for e in d.values()) for d in self.atom_lit.values()):
            if VERBOSE > 0: print("Done")
            print(self.grid.get_str())
            self.done = True
            return

        if VERBOSE <= 2: print(self.grid.get_str())
        if VERBOSE > 0: print("PROPAGATE:")
        if VERBOSE > 1: print(" Previous", changes)

        # If not done, check whether current state is possible
        if self._check_answers:
            if VERBOSE > 0: print(" LLM Checking State")

            found_impossible = False
            for i,r in enumerate(self.row):
                question = r + ": " + "".join(self.grid.get()[i])
                if VERBOSE > 2: print("QUESTION", question)
                answer = self.llm.question(question).lower()
                if VERBOSE > 2: print("ANSWER", answer)
                if "impossible" in answer:
                    found_impossible = True
                    break

            for i,r in enumerate(self.col):
                if found_impossible:
                    break
                question = r + ": " + "".join([row[i] for row in self.grid.get()])
                if VERBOSE > 2: print("QUESTION:", question)
                answer = self.llm.question(question).lower()
                if VERBOSE > 2: print("ANSWER", answer)
                if "impossible" in answer:
                    found_impossible = True

            if found_impossible:
                if VERBOSE > 0: print(" Impossible")
                control.add_nogood([lit for lit in self.lit_thought if control.assignment.is_true(lit)])
                control.propagate()
                return

        self.thought_structure(control,changes)

        # # If there are no more thoughts to pick, the current state is illegal
        # if not any(control.assignment.is_free(lit) for lit in self.lit_thought):
        #     if VERBOSE > 0: print(" No more thoughts.")
        #     control.add_nogood([lit for lit in self.lit_thought if control.assignment.is_true(lit)])

        control.propagate()

    def check(self, control):
        # Interrupt checking if at least one letter holds true for every field
        if all(all(any(control.assignment.is_true(i) for i in e.values()) for e in d.values()) for d in self.atom_lit.values()):
            return

        if VERBOSE > 0: print("CHECK")
        if not any(control.assignment.is_free(lit) for lit in self.lit_thought):
            if VERBOSE > 1: print(" No thoughts!")
            control.add_nogood([lit for lit in self.lit_thought if control.assignment.is_true(lit)])
            control.propagate()

    def undo(self, thread_id, assignment, changes):
        if not self.done:
            if VERBOSE > 0:
                print("UNDO:")
                print(changes)
            for _ in changes:
                self.grid.back()
            # for c in changes:
            #     if c in self.lit_thought:
            #         del self.lit_thought[c]

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
        options.add_flag(group, 'check', "Let the LLM check the possibility of answers", self._check_answers)

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
