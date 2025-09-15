import json

# Load crosswords from JSON file
with open("original.json", "r") as f:
    data = json.load(f)

for i,d in enumerate(data):
    with open(f"instances/ins_{i:0>{3}}.lp", "w") as f:
        f.write(f"% Instance {i}\n\n% Prompts\n")
        
        for j,prompt in enumerate(d[0][0:5]):
            f.write(f"row({j},\"{prompt}\").\n")

        for j,prompt in enumerate(d[0][5:10]):
            f.write(f"col({j},\"{prompt}\").\n")

        f.write("\n% Solution\n")

        for j in range(5):
            for k in range(5):
                f.write(f"sol({j},{k},\"{d[1][j*5+k]}\").\n")
