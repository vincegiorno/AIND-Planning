from aimacode.logic import PropKB
from aimacode.planning import Action
from aimacode.search import (
    Node, Problem,
)
from aimacode.utils import expr
from lp_utils import (
    FluentState, encode_state, decode_state,
)
from my_planning_graph import PlanningGraph

from functools import lru_cache

import re

class AirCargoProblem(Problem):
    def __init__(self, cargos, planes, airports, initial: FluentState, goal: list):
        """

        :param cargos: list of str
            cargos in the problem
        :param planes: list of str
            planes in the problem
        :param airports: list of str
            airports in the problem
        :param initial: FluentState object
            positive and negative literal fluents (as expr) describing initial state
        :param goal: list of expr
            literal fluents required for goal test
        """
        self.state_map = initial.pos + initial.neg
        self.initial_state_TF = encode_state(initial, self.state_map)
        Problem.__init__(self, self.initial_state_TF, goal=goal)
        self.cargos = cargos
        self.planes = planes
        self.airports = airports
        self.actions_list = self.get_actions()

    def get_actions(self):
        """
        This method creates concrete actions (no variables) for all actions in the problem
        domain action schema and turns them into complete Action objects as defined in the
        aimacode.planning module. It is computationally expensive to call this method directly;
        however, it is called in the constructor and the results cached in the `actions_list` property.

        Returns:
        ----------
        list<Action>
            list of Action objects
        """

        def load_actions():
            """Create all concrete Load actions and return a list

            :return: list of Action objects
            """
            loads = []
            # Generate all possible combinations of cargo, plane and airport
            for c in self.cargos:
                for p in self.planes:
                    for a in self.airports:
                        # Plane and cargo at same airport are the positive preconditions
                        precond_pos = [expr("At({}, {})".format(p, a)),
                            expr("At({}, {})".format(c, a))]
                        precond_neg = []
                        # Effects will be cargo in plane and no longer at airport
                        effect_add = [expr("In({}, {})".format(c, p))]
                        effect_rem = [expr("At({}, {})".format(c, a))]
                        load = Action(expr("Load({}, {}, {})".format(c, p, a)),
                                     [precond_pos, precond_neg],
                                     [effect_add, effect_rem])
                        loads.append(load)
            return loads

        def unload_actions():
            """Create all concrete Unload actions and return a list

            :return: list of Action objects
            """
            unloads = []
            for c in self.cargos:
                for p in self.planes:
                    for a in self.airports:
                        # Plane at airport and cargo in plane are the positive preconditions
                        precond_pos = [expr("At({}, {})".format(p, a)),
                            expr("In({}, {})".format(c, p))]
                        precond_neg = []
                        # Effects are cargo at airport and no longer in plane
                        effect_add = [expr("At({}, {})".format(c, a))]
                        effect_rem = [expr("In({}, {})".format(c, p))]
                        unload = Action(expr("Unload({}, {}, {})".format(c, p, a)),
                                     [precond_pos, precond_neg],
                                     [effect_add, effect_rem])
                        unloads.append(unload)
            return unloads

        def fly_actions():
            """Create all concrete Fly actions and return a list

            :return: list of Action objects
            """
            flys = []
            # Generate all possible combinations of 'from' and 'to' airports together with planes
            for fr in self.airports:
                for to in self.airports:
                    # Plane can't fly to same airport it leaves from
                    if fr != to:
                        for p in self.planes:
                            # PLane at airport is the only precondition
                            precond_pos = [expr("At({}, {})".format(p, fr))]
                            precond_neg = []
                            # Effects are plane at 'to' airport and no longer at 'from' airport
                            effect_add = [expr("At({}, {})".format(p, to))]
                            effect_rem = [expr("At({}, {})".format(p, fr))]
                            fly = Action(expr("Fly({}, {}, {})".format(p, fr, to)),
                                         [precond_pos, precond_neg],
                                         [effect_add, effect_rem])
                            flys.append(fly)
            return flys

        return load_actions() + unload_actions() + fly_actions()

    def actions(self, state: str) -> list:
        """ Return the actions that can be executed in the given state.

        :param state: str
            state represented as T/F string of mapped fluents (state variables)
            e.g. 'FTTTFF'
        :return: list of Action objects
        """
        def all_in(list1, list2):
            """
            Returns True if all elements in list1 are in list2
            """
            for item in list1:
                if item not in list2:
                    return False
            return True

        fluents = decode_state(state, self.state_map) # Retrieve the state's fluents as expressions
        possible_actions = []
        for action in self.actions_list:
            # Action is possible if all positive and negative preconditions are among the fluents
            if all_in(action.precond_pos, fluents.pos) and all_in(action.precond_neg, fluents.neg):
                possible_actions.append(action)
        return possible_actions

    def result(self, state: str, action: Action):
        """ Return the state that results from executing the given
        action in the given state. The action must be one of
        self.actions(state).

        :param state: state entering node
        :param action: Action applied
        :return: resulting state after action
        """
        fluents = decode_state(state, self.state_map)
        pos = fluents.pos
        neg = fluents.neg
        # Add positive effects to positive fluents & remove from negative; vice-versa for negative effects
        for effect in action.effect_add:
            if effect in neg:
                neg.remove(effect)
            if effect not in pos:
                pos.append(effect)
        for effect in action.effect_rem:
            if effect in pos:
                pos.remove(effect)
            if effect not in neg:
                neg.append(effect)

        new_state = FluentState(pos, neg)
        return encode_state(new_state, self.state_map)

    def goal_test(self, state: str) -> bool:
        """ Test the state to see if goal is reached

        :param state: str representing state
        :return: bool
        """
        kb = PropKB()
        kb.tell(decode_state(state, self.state_map).pos_sentence())
        for clause in self.goal:
            if clause not in kb.clauses:
                return False
        return True

    def h_1(self, node: Node):
        # note that this is not a true heuristic
        h_const = 1
        return h_const

    @lru_cache(maxsize=8192)
    def h_pg_levelsum(self, node: Node):
        """This heuristic uses a planning graph representation of the problem
        state space to estimate the sum of all actions that must be carried
        out from the current state in order to satisfy each individual goal
        condition.
        """
        # requires implemented PlanningGraph class
        pg = PlanningGraph(self, node.state)
        pg_levelsum = pg.h_levelsum()
        return pg_levelsum

    @lru_cache(maxsize=8192)
    def h_ignore_preconditions(self, node: Node):
        """This heuristic estimates the minimum number of actions that must be
        carried out from the current state in order to satisfy all of the goal
        conditions by ignoring the preconditions required for an action to be
        executed.
        """
        fluents = decode_state(node.state, self.state_map)
        pos = fluents.pos
        count = 0
        regex = r'(\w+)' # Matches stringified action and parameter symbols
        for goal in self.goal:
            # Only process unmet goals
            if goal not in pos:
                _, c, a = re.findall(regex, str(goal)) # Don't need action string since all goals are 'At' expressions
                in_plane = False
                for p in self.planes:
                    # If cargo is in plane, add 1 to count if plane is at the correct airport ('Unload')
                    if expr("In({}, {})".format(c, p)) in pos:
                        in_plane = True
                        if expr("At({}, {})".format(p, a)) in pos:
                            count += 1
                        # Add 2 to count if plane is not at the correct airport ('Fly' + 'Unload')
                        else:
                            count += 2
                        break
                # Add 3 to count if cargo not in plane ('Load', 'Fly', 'Unload')
                if not in_plane:
                    count += 3
        return count


def air_cargo_p1() -> AirCargoProblem:
    cargos = ['C1', 'C2']
    planes = ['P1', 'P2']
    airports = ['JFK', 'SFO']
    pos = [expr('At(C1, SFO)'),
           expr('At(C2, JFK)'),
           expr('At(P1, SFO)'),
           expr('At(P2, JFK)'),
           ]
    neg = [expr('At(C2, SFO)'),
           expr('In(C2, P1)'),
           expr('In(C2, P2)'),
           expr('At(C1, JFK)'),
           expr('In(C1, P1)'),
           expr('In(C1, P2)'),
           expr('At(P1, JFK)'),
           expr('At(P2, SFO)'),
           ]
    init = FluentState(pos, neg)
    goal = [expr('At(C1, JFK)'),
            expr('At(C2, SFO)'),
            ]
    return AirCargoProblem(cargos, planes, airports, init, goal)


def air_cargo_p2() -> AirCargoProblem:
    cargos = ['C1', 'C2', 'C3']
    planes = ['P1', 'P2', 'P3']
    airports = ['JFK', 'SFO', 'ATL']
    pos = [expr('At(C1, SFO)'),
           expr('At(C2, JFK)'),
           expr('At(C3, ATL)'),
           expr('At(P1, SFO)'),
           expr('At(P2, JFK)'),
           expr('At(P3, ATL)'),
           ]
    neg = [expr('At(C1, ATL)'),
           expr('At(C1, JFK)'),
           expr('At(C2, ATL)'),
           expr('At(C2, SFO)'),
           expr('At(C3, JFK)'),
           expr('At(C3, SFO)'),
           expr('In(C1, P1)'),
           expr('In(C1, P2)'),
           expr('In(C1, P3)'),
           expr('In(C2, P1)'),
           expr('In(C2, P2)'),
           expr('In(C2, P3)'),
           expr('In(C3, P1)'),
           expr('In(C3, P2)'),
           expr('In(C3, P3)'),
           expr('At(P1, ATL)'),
           expr('At(P1, JFK)'),
           expr('At(P2, ATL)'),
           expr('At(P2, SFO)'),
           expr('At(P3, JFK)'),
           expr('At(P3, SFO)'),
           ]
    init = FluentState(pos, neg)
    goal = [expr('At(C1, JFK)'),
            expr('At(C2, SFO)'),
            expr('At(C3, SFO)'),
            ]
    return AirCargoProblem(cargos, planes, airports, init, goal)


def air_cargo_p3() -> AirCargoProblem:
    cargos = ['C1', 'C2', 'C3', 'C4']
    planes = ['P1', 'P2']
    airports = ['JFK', 'SFO', 'ATL', 'ORD']
    pos = [expr('At(C1, SFO)'),
           expr('At(C2, JFK)'),
           expr('At(C3, ATL)'),
           expr('At(C4, ORD)'),
           expr('At(P1, SFO)'),
           expr('At(P2, JFK)'),
           ]
    neg = [expr('At(C1, ATL)'),
           expr('At(C1, JFK)'),
           expr('At(C1, ORD)'),
           expr('At(C2, ATL)'),
           expr('At(C2, ORD)'),
           expr('At(C2, SFO)'),
           expr('At(C3, JFK)'),
           expr('At(C3, ORD)'),
           expr('At(C3, SFO)'),
           expr('At(C4, ATL)'),
           expr('At(C4, JFK)'),
           expr('At(C4, SFO)'),
           expr('In(C1, P1)'),
           expr('In(C1, P2)'),
           expr('In(C2, P1)'),
           expr('In(C2, P2)'),
           expr('In(C3, P1)'),
           expr('In(C3, P2)'),
           expr('In(C4, P1)'),
           expr('In(C4, P2)'),
           expr('At(P1, ATL)'),
           expr('At(P1, JFK)'),
           expr('At(P1, ORD)'),
           expr('At(P2, ATL)'),
           expr('At(P2, ORD)'),
           expr('At(P2, SFO)'),
           ]
    init = FluentState(pos, neg)
    goal = [expr('At(C1, JFK)'),
            expr('At(C3, JFK)'),
            expr('At(C2, SFO)'),
            expr('At(C4, SFO)'),
            ]
    return AirCargoProblem(cargos, planes, airports, init, goal)


