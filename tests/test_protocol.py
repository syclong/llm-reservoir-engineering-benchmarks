"""Check budgets, information boundaries, and scoring offline."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from fopt5.__main__ import scoreboard
from fopt5.design import BASE, ROOT, WELLS, canonical, digest, dump, parse_plan, read_json, render, write
from fopt5.experiment import count_budget, directory, model_request, prompt, round_once


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.plan=read_json(ROOT/"examples/output_format.json")
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.study=Path(temp.name)

    def test_full_deck_and_28_values(self):
        self.assertEqual(render(self.plan),BASE.read_text(encoding="utf-8"))
        self.assertEqual(sum(len(a) for a in self.plan.values()),28)
        first=prompt(self.study,"llm",[])
        self.assertEqual(first,(ROOT/"prompts/round_1_complete.txt").read_text(encoding="utf-8"))
        self.assertEqual(first.count(BASE.read_text(encoding="utf-8")),1)

    def test_publication_language_and_generated_script(self):
        import re
        from build_release import MATERIAL, RUNTIME, standalone

        cjk = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3000-\u303f\uff01-\uff60]")
        for name in [*RUNTIME, *MATERIAL, "fopt5_llm_loop.py"]:
            with self.subTest(file=name):
                self.assertIsNone(cjk.search(name))
                self.assertIsNone(cjk.search((ROOT / name).read_text(encoding="utf-8")))
        self.assertEqual((ROOT / "fopt5_llm_loop.py").read_bytes(), standalone())

    def test_invalid_and_equivalent_proposals(self):
        for wrong in ([[0,13],None], [[15,13],[100,100,100,100,100]]):
            p=copy.deepcopy(self.plan)
            p["INJ1"][:2]=wrong[0]
            if wrong[1]:p["INJ1"][2:]=wrong[1]
            with self.assertRaises(ValueError):parse_plan(dump(p))
        p=copy.deepcopy(self.plan)
        p["PROD1"][:2]=p["INJ1"][:2]
        with self.assertRaises(ValueError):parse_plan(dump(p))
        with self.assertRaises(ValueError):parse_plan('{"INJ1":[],"INJ1":[]}')
        p=copy.deepcopy(self.plan);p["INJ1"],p["INJ2"]=p["INJ2"],p["INJ1"]
        self.assertEqual(canonical(self.plan),canonical(p))

    def test_later_prompt_contains_own_memory_and_only_last_feedback(self):
        records=[]
        for i in (1,2):
            raw=f"OWN_ONLY_{i}_FIELD"
            write(directory(self.study,"llm",i)/"feedback.txt",raw)
            records.append({"round":i,"status":"ok","plan":self.plan,"fopt_sm3":i*123,"feedback_sha256":digest(raw.encode())})
        write(directory(self.study,"pso",2)/"feedback.txt","UNRELATED_OTHER_ARM")
        text=prompt(self.study,"llm",records)
        self.assertIn(" | 123",text);self.assertIn(" | 246",text)
        self.assertIn("OWN_ONLY_2_FIELD",text);self.assertNotIn("OWN_ONLY_1_FIELD",text);self.assertNotIn("UNRELATED_OTHER_ARM",text)
        self.assertNotIn("OWN_ONLY_2_FIELD",prompt(self.study,"llm_scalar",records))
        template=(ROOT/"prompts/round_3_template.txt").read_text(encoding="utf-8")
        for row in records:
            line=" | ".join([str(row["round"]),"ok",*[dump(row["plan"][w]) for w in WELLS],str(row["fopt_sm3"])])
            template=template.replace("{{ROUND_"+str(row["round"])+"_OBSERVATION}}",line)
        self.assertEqual(template.replace("{{PREVIOUS_ROUND_FULL_FEEDBACK_OR_STATUS}}","OWN_ONLY_2_FIELD"),text)
        last_failed=records+[{"round":3,"status":"invalid"}]
        self.assertNotIn("OWN_ONLY_2_FIELD",prompt(self.study,"llm",last_failed))

    def test_proposal_budget_and_failure_not_zero(self):
        with self.assertRaises(ValueError):
            round_once(self.study,"pso",[{}]*5,None,1)
        for arm,values in [("pso",[10,40,30,12,20]),("llm",[15,17,43,12,None])]:
            for n,score in enumerate(values,1):
                rec={"round":n,"arm":arm,"status":"ok" if score is not None else "invalid","simulator_calls":int(score is not None)}
                if score is not None:rec["fopt_sm3"]=score
                write(directory(self.study,arm,n)/"record.json",dump(rec))
        s=scoreboard(self.study)
        self.assertEqual(s["winner"],"llm")
        self.assertEqual(s["delta_llm_minus_pso_sm3"],3);self.assertIsNone(s["arms"]["llm"]["round5_actual_sm3"])
        self.assertEqual(s["arms"]["llm"]["actual_simulator_calls"],4)

    def test_model_selection_has_exactly_one_field(self):
        self.assertTrue((ROOT/"model.json").is_file(), "A single-field model file is required")
        from fopt5.settings import model_name
        published = read_json(ROOT/"model.json")
        self.assertEqual(published, {"model": model_name()})
        sample = self.study/"sample.json"
        for item in ({"model": ""}, {"model": "a", "extra": "b"}, {"model": "--other"}, []):
            write(sample, dump(item))
            with self.assertRaises(ValueError):
                model_name(sample)

    def test_model_file_rejects_a_repeated_field(self):
        from fopt5.settings import model_name
        sample = self.study / "model.json"
        write(sample, '{"model":"first","model":"second"}')
        with self.assertRaises(ValueError):
            model_name(sample)

    def test_model_registration_rejects_non_text(self):
        from fopt5.experiment import register_model
        with self.assertRaises(ValueError):
            register_model(self.study, {"extra":"value"})
        self.assertFalse((self.study/"llm/model.json").exists())

    def test_fresh_command_and_utf8_budget(self):
        from fopt5 import experiment
        self.assertTrue(hasattr(experiment, "find_model_command"), "Run one local command per proposal")
        text = "Well placement and cumulative oil (sm³)"
        reply = dump(self.plan)
        with patch.object(experiment, "find_model_command", return_value="local-llm"), \
             patch.object(experiment.subprocess, "run", return_value=subprocess.CompletedProcess([],0,reply.encode())) as run:
            self.assertEqual(model_request("test-model", text),reply)
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["local-llm","prompt","--model","test-model","--no-stream","--no-log"])
        self.assertEqual(kwargs["input"], text.encode("utf-8"))
        self.assertFalse(kwargs["shell"])
        self.assertEqual(count_budget(text)["input_count_or_upper_bound"], len(text.encode("utf-8")))
        with self.assertRaises(ValueError):
            count_budget("µ"*500_000)

    def test_registration_pins_only_the_model_name(self):
        from fopt5 import experiment
        self.assertTrue(hasattr(experiment, "register_model"), "The registration must record the model name")
        experiment.register_model(self.study, "test-model")
        self.assertEqual(read_json(self.study/"llm/model.json"), {"model":"test-model"})
        with self.assertRaises(ValueError):
            experiment.register_model(self.study, "changed-model")

    def test_manual_round_works_without_a_local_client(self):
        from fopt5 import experiment
        self.assertTrue(hasattr(experiment, "find_model_command"), "Manual submission must work independently")
        file=self.study/"submitted.txt"
        write(file, "{}")
        with patch.object(experiment,"find_model_command",side_effect=AssertionError("unexpected inference")):
            row=round_once(self.study,"llm",[],None,1,model="test-model",manual=file)
        self.assertEqual((row["model"],row["status"],row["simulator_calls"]),("test-model","invalid",0))

    def test_missing_client_does_not_consume_a_round(self):
        from fopt5 import experiment
        self.assertTrue(hasattr(experiment, "find_model_command"), "Check for the local client before dispatch")
        with patch.object(experiment,"find_model_command",side_effect=FileNotFoundError("local client unavailable")):
            with self.assertRaises(FileNotFoundError):
                round_once(self.study,"llm",[],None,1,model="test-model")
        self.assertFalse(directory(self.study,"llm",1).exists())


if __name__=="__main__":
    unittest.main(verbosity=2)
