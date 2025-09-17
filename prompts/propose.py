history = [{
    "role":"assistant",
    "content": "Sure here are some options:\nh0. TASKS (high)\nh1. WIRED (medium)\nh2. REVEL (certain)\nh3. AWAKE (certain)\nh4. ACTIV (high)\nv0. MINTY (low)\nv3. NEVER (certain)\nv4. WRECK (high)"
}]

message = {
    "role": "user",
    "content":"""Let's play a 5 x 5 mini crossword, where each word should have exactly 5 letters.

{input}

Given the current status, list all possible answers for unfilled or changed words, and your confidence levels (certain/high/medium/low), using the format "h1. APPLE (medium)". Use "certain" cautiously and only when you are 100% sure this is the correct word. You can list more then one possible answer for each word, but use a new line for each word and use the previous format."""
}
