import processscheduler as ps
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
import json

app = Flask(__name__)
cors = CORS(app)

@app.errorhandler(404)
def resource_not_found(e):
    return make_response(jsonify(error='Not found!'), 404)


################################################
#############     Input Data    ################
################################################

"""
| p | Time  | g1 | g2 | g3 | prof |
___________________________________
| 0 | 8am   |  X | X  | X  |      | 
| 1 | 8:30  |  X | X  |    |      | 
| 2 | 9am   |    |    |    |      | 
| 3 | 9:30  |    |    |    |      | 
| 4 | 10am  |  X | X  |    |      | 
| 5 | 10:30 |  X | X  |    |      | 
| 6 | 11am  |    | X  |    |      | 
| 7 | 11:30 |    | X  |    |      | 
| 8 | 12pm  |    |    |    | X    | 
| 9 | 12:30 |    |    |    | X    | 
___________________________________
"""
period = 0.5  # hours of the smallest time unit we will use
horizon = 10 # how many time periods included in the problem
lesson_duration = 2  # lesson duration in periods
students = {
    "tim beccue": [0,1,4,5],
    "william gu": [0,1,4,5,6,7],
    "allison wang": [0],
}
prof = {
    "name": "Michael Kannen",
    "busy": [8,9]
}

################################################
#############    Flask Server   ################
################################################

@app.route('/')
def hello():
    return jsonify(message='Hello, World!')

@app.route('/add', methods=['POST'])
def add():
    data = request.get_json()
    a = data['a']
    b = data['b']
    c = a + b

    return jsonify(result=c)

@app.route('/solve', methods=['POST'])
def solve():
    data = request.get_json()

    students = data['students']
    schedule_config = data['scheduleConfig']
    general_busy_times = data['generalBusyTimes']
    prof = data['prof']
    prof["busy"] += general_busy_times  # consolidate all non-schedulable periods into one place

    periods_per_day = schedule_config["periodsPerDay"]
    days = schedule_config["days"]
    horizon = periods_per_day * len(days)
    lesson_duration = schedule_config["lessonDuration"]
    
    # Compute the periods lessons cannot start because they would cross into the next day
    late_start_periods = get_late_start_periods(lesson_duration, periods_per_day, len(days))

    # Use a set so we don't have duplicates
    all_solutions = set([])

    problem = create_problem("toy_scheduling_scenario", horizon)
    tasks, worker, solver = configure_problem_details(
            problem, 
            prof, 
            students, 
            lesson_duration, 
            late_start_periods)
    solution = solver.solve()   # initial solve

    result = {
        "solutionFound": True if solution else False,
        "solution": format_solution(solution)
    }
    return result


@app.route('/solveall', methods=['POST'])
def solveall():
    data = request.get_json()

    students = data['students']
    schedule_config = data['scheduleConfig']
    general_busy_times = data['generalBusyTimes']
    prof = data['prof']
    prof["busy"] += general_busy_times  # consolidate all non-schedulable periods into one place

    periods_per_day = schedule_config["periodsPerDay"]
    days = schedule_config["days"]
    horizon = periods_per_day * len(days)
    lesson_duration = schedule_config["lessonDuration"]
    
    # Compute the periods lessons cannot start because they would cross into the next day
    late_start_periods = get_late_start_periods(lesson_duration, periods_per_day, len(days))

    # Use a set so we don't have duplicates
    all_solutions = set([])

    for i in range(len(students)):
        problem = create_problem("toy_scheduling_scenario", horizon)
        tasks, worker, solver = configure_problem_details(
                problem, 
                prof, 
                students, 
                lesson_duration, 
                late_start_periods)
        local_solutions = get_all_solutions(solver, tasks[i])

        # Add solutions to our set
        for s in local_solutions:
            # Dicts can't be hashed, but hack that by recursively sorting and stringifying the dict.
            #all_solutions.add(json.dumps(s, sort_keys=True))
            all_solutions.add(json.dumps(s))

    # Convert the set of strings into an array of dicts so it can be jsonified and returned
    all_solutions = [json.loads(s) for s in list(all_solutions)]

    result = {
        "solutionFound": False,
        "solutions": []
    }

    if len(all_solutions) > 0:
        result["solutionFound"] = True
        result["solutions"] = all_solutions

    return result


################################################
#############     Scheduling    ################
################################################

# TODO: refactor into class so it's cleaner accessing the workers, tasks, solver, etc.

def create_problem(name, horizon):
    problem = ps.SchedulingProblem(name, horizon=horizon)
    return problem

def get_late_start_periods(lesson_duration, periods_per_day, num_days):
    """ This function returns the period indexes where starting a lesson
    during that time would involve the lesson extending beyond the last free period in the day. 
    """

    # Can't cross day boundary if lesson duration is just one period
    if lesson_duration <= 1: 
        return []

    # First solve for the first day boundary. Then it's easy to extend for n days. 
    last_period_in_day = periods_per_day - 1
    one_day_late_periods = [last_period_in_day - length for length in range(lesson_duration - 1)]

    # Extrapolate to all days
    late_periods = []
    for days in range(num_days):
        for period in one_day_late_periods:
            late_periods.append(period + (periods_per_day * days))
    return late_periods 


def configure_problem_details(problem, prof, groups, lesson_duration, late_start_periods, optimize=False):

    # Define the prof to be a worker able to teach one lesson at a time. 
    worker = ps.Worker(prof["name"], productivity=1)
    tasks = []

    # Define a lesson "task" for each group that needs scheduling
    for group in groups:
        lesson = ps.FixedDurationTask(group["name"], duration=lesson_duration)
        tasks.append(lesson)

        # Add constraints defining when groups cannot start based on their provided busy periods
        for busy_period in group["busy"]:
            # Lessons may not start such that they cross over a busy period
            for i in range(lesson_duration):
                problem.add_constraint(lesson.start != busy_period - i)

        # Prevent lesson from starting too close to the end of the day
        for period in late_start_periods:
            problem.add_constraint(lesson.start != period)

        # Assign the group to the professor who will teach them
        lesson.add_required_resource(worker)

    # Apply busy periods for the prof
    capacity = 0  # block time by setting the prof's work capacity to 0
    for busy_period in prof["busy"]:
        start = busy_period
        end   = busy_period + 1
        ps.WorkLoad(worker, {(start, end): capacity})


    if optimize: 
        problem.add_objective_makespan()
        #problem.add_objective_flowtime()

    solver = ps.SchedulingSolver(problem, random_values=True, optimizer="incremental", max_time=3)

    return (tasks, worker, solver)

def format_solution(solution):
    if not solution: return False
    formatted_solution = {}
    scheduled_tasks = solution.get_scheduled_tasks()
    for s in scheduled_tasks:
        task = scheduled_tasks[s]
        formatted_solution[task.name] = [task.start + n for n in range(task.duration)]
    return formatted_solution

def get_all_solutions(solver, task):
    solutions = []
    solution = solver.solve()   # initial solve
    while solution:             # repeat until failure
        solutions.append(format_solution(solution))
        solution = solver.find_another_solution(task.start)
    return solutions
        
def plot_solution(problem):
    solver = ps.SchedulingSolver(problem)
    solution = solver.solve()
    if solution:
        solution.render_gantt_matplotlib() # default render_mode is 'Resource'
