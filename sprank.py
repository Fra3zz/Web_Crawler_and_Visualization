import sqlite3

conn = sqlite3.connect('spider.sqlite')
cur = conn.cursor()

# Find the ids that send out page rank - we only are interested
# in pages in the SCC (Strongly Connected Component) that have both in and out links
cur.execute('''SELECT DISTINCT from_id FROM Links WHERE from_id IN (SELECT to_id FROM Links)''')
from_ids = [row[0] for row in cur]

if not from_ids:
    print("No suitable pages found for PageRank calculation.")
    cur.close()
    quit()

# Initialize link structures and ranks dictionaries
links = {}
prev_ranks = {}
for from_id in from_ids:
    cur.execute('''SELECT new_rank FROM Pages WHERE id = ?''', (from_id,))
    row = cur.fetchone()
    # Ensure a default rank of 1.0 if the fetched rank is None
    prev_ranks[from_id] = row[0] if row[0] is not None else 1.0
    links[from_id] = []

# Fetch the links only between pages that are both in from_ids
cur.execute('''SELECT from_id, to_id FROM Links WHERE from_id IN (SELECT to_id FROM Links)''')
for from_id, to_id in cur:
    if from_id != to_id and to_id in from_ids:
        links[from_id].append(to_id)

# PageRank algorithm iterations
sval = input('How many iterations: ')
many = 1 if not sval.isdigit() else int(sval)

for i in range(many):
    next_ranks = {node: 0.0 for node in from_ids}
    total = sum(prev_ranks.values())

    # Distribute ranks from each page
    for node, old_rank in prev_ranks.items():
        give_ids = links[node]
        if give_ids:
            amount = old_rank / len(give_ids)
            for id in give_ids:
                next_ranks[id] += amount

    # Apply damping factor and normalize by adding 'lost' rank back uniformly
    new_total = sum(next_ranks.values())
    damping_factor = 0.85
    lost_rank = (1 - damping_factor) * (total / len(next_ranks))
    next_ranks = {node: rank * damping_factor + lost_rank for node, rank in next_ranks.items()}

    # Check convergence (this could be used to stop early if changes are below a threshold)
    avediff = sum(abs(prev_ranks[node] - next_ranks[node]) for node in from_ids) / len(from_ids)
    print(f"Iteration {i+1}: Average difference = {avediff}")

    prev_ranks = next_ranks

# Update the database with the new ranks
cur.execute('''UPDATE Pages SET old_rank=new_rank''')
for id, new_rank in next_ranks.items():
    cur.execute('''UPDATE Pages SET new_rank=? WHERE id=?''', (new_rank, id))
conn.commit()

cur.close()
