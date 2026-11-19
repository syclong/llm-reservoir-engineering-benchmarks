"""Generate full prompt templates with the complete DATA and placeholders for future observations."""
from fopt5.design import ROOT, write
from fopt5.experiment import prompt


def materialize():
    target=ROOT/"prompts"
    first=prompt(ROOT/"runs/main","llm",[])
    write(target/"round_1_complete.txt",first)
    body,tail=first.rsplit("[END OF INPUT FOR ROUND 1]",1)
    for r in range(2,6):
        memory=["[HISTORY OF THIS ARM] Each row contains the round, status, INJ1, INJ2, PROD1, PROD2, and FOPT (sm³), in that order. NA means unavailable."]
        memory.extend("{{ROUND_"+str(n)+"_OBSERVATION}}" for n in range(1,r))
        memory.extend(["[SIMULATION FEEDBACK FROM THE PRECEDING ROUND]","{{PREVIOUS_ROUND_FULL_FEEDBACK_OR_STATUS}}"])
        text=body.replace("Proposal round 1/5",f"Proposal round {r}/5")+"\n".join(memory)+f"\n[END OF INPUT FOR ROUND {r}]"+tail
        write(target/f"round_{r}_template.txt",text)


if __name__=="__main__":
    materialize()
