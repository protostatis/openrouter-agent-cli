lines = open("emails.txt").read().splitlines()
print("UNIQUE:", len(set(lines)))
