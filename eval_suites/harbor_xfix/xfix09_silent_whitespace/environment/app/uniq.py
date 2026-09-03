lines = open("signups.txt").read().splitlines()
print("UNIQUE:", len(set(lines)))
