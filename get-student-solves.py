import requests
from datetime import datetime, timezone

#
# Use the pwn.college API at:
#    https://pwn.college/pwncollege_api/v1/dojos/linux-luminarium/solves?username=<username>
# to get a list of all solves for a user on a specific dojo.
#
# The output will be a JSON object containing the list of solves, e.g.:
# {
#   "success": true,
#   "solves": [
#     {
#       "timestamp": "2024-06-04T20:08:58.500843+00:00",
#       "module_id": "paths",
#       "challenge_id": "root"
#     },
#     {
#       "timestamp": "2025-08-22T01:11:18.284826+00:00",
#       "module_id": "hello",
#       "challenge_id": "hello"
#     },
#     {
#       "timestamp": "2025-08-22T01:21:37.669606+00:00",
#       "module_id": "piping",
#       "challenge_id": "echo"
#     }
#   ]
# }
#
# Inputs:
# - username: The username of the student to retrieve solves for.
# - dojo: The dojo to retrieve solves from.
#
# Output: a dictionary organizing the solves by module, where each module entry is
# a dictionary mapping each solved challenge to the datetime object when it was solved.
def get_student_solves(username, dojo):
    # Call the API to get the solves
    response = requests.get(f"https://pwn.college/pwncollege_api/v1/dojos/{dojo}/solves?username={username}")
    data = response.json()

    if not data.get("success"):
        return {}

    solves = data.get("solves", [])
    solves_dict = {}
    for solve in solves:
        module = solve["module_id"]
        challenge = solve["challenge_id"]
        timestamp_str = solve["timestamp"]
        # Parse timestamp to datetime object
        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        if module not in solves_dict:
            solves_dict[module] = {}
        solves_dict[module][challenge] = timestamp
    return solves_dict

def get_all_challenges(dojo):
    response = requests.get(f"https://pwn.college/pwncollege_api/v1/dojos/{dojo}/modules")
    data = response.json()
    if not data.get("success"):
        return {}
    modules = data.get("modules", [])
    challenges_dict = {}
    for module in modules:
        module_id = module["id"]
        challenges = [ch["id"] for ch in module["challenges"]]
        challenges_dict[module_id] = challenges
    return challenges_dict

# Output: a human-readable summary including:
#   * The total number of solves
#   * A list of all unique module IDs solved
#   * A list of all unique challenge IDs solved
#   * A list of each solved challenge with the time it was solved
#   * Per-module and overall summaries of solves before the deadline
def grade_student(username, dojo, deadline):
    solves_dict = get_student_solves(username, dojo)
    all_challenges = get_all_challenges(dojo)
    if not all_challenges:
        print("Failed to retrieve challenges.")
        return

    total_solves = sum(len(challenges) for challenges in solves_dict.values())
    module_ids = list(solves_dict.keys())
    challenge_ids = set()
    for challenges in solves_dict.values():
        challenge_ids.update(challenges.keys())

    # Print the summary
    print(f"Total solves: {total_solves}")
    print(f"Unique module IDs: {', '.join(module_ids)}")
    print(f"Unique challenge IDs: {', '.join(challenge_ids)}")
    print("\nSolved challenges:")
    
    overall_before_deadline = 0
    total_challenges = sum(len(ch) for ch in all_challenges.values())
    
    for module in all_challenges:
        print(f"Module: {module}")
        challenges_solved = solves_dict.get(module, {})
        module_before_deadline = 0
        for challenge, timestamp in challenges_solved.items():
            # Format datetime to human-readable string
            formatted_timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            print(f"  {challenge}: {formatted_timestamp}")
            if timestamp < deadline:
                module_before_deadline += 1
        total_in_module = len(all_challenges[module])
        overall_before_deadline += module_before_deadline
        percentage = (module_before_deadline / total_in_module) * 100 if total_in_module > 0 else 0
        print(f"{module_before_deadline}/{total_in_module} solved before deadline ({percentage:.1f}%)")
    
    overall_percentage = (overall_before_deadline / total_challenges) * 100 if total_challenges > 0 else 0
    print(f"\nOverall: {overall_before_deadline}/{total_challenges} solved before deadline ({overall_percentage:.1f}%)")

if __name__ == "__main__":
    username = input("Enter the student's username: ")
    dojo = input("Enter the dojo name: ")
    deadline_str = input("Enter the deadline in UTC (YYYY-MM-DD HH:MM:SS): ")
    deadline = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M:%S")
    deadline = deadline.replace(tzinfo=timezone.utc)
    grade_student(username, dojo, deadline)