"""I/O and one-message transport boundary tests. These fixtures never run a simulator or a model."""
from io import BytesIO
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import subprocess
import punq_history_match as hm


class BoundaryTests(unittest.TestCase):
    def test_one_plain_text_call_no_tools_or_attachments(self):
        with TemporaryDirectory() as temp:
            work=Path(temp)
            text="All data in one message.\nOil in sm³/day.\n"
            hm.write(work/"prompt.txt",text)
            base={"prompt_sha256":hm.sha(text.encode("utf-8"))}
            reply='{"edits":[]}'
            with patch.object(hm.shutil,"which",return_value="llm-test"), patch.object(
                hm.subprocess,"run",return_value=subprocess.CompletedProcess([],0,reply.encode())) as run:
                got=hm.collect_proposal(work,base)
                self.assertEqual(got,reply)
                self.assertEqual(hm.collect_proposal(work,base),reply)
            self.assertEqual(run.call_count,1)
            args,kw=run.call_args
            self.assertEqual(args[0],["llm-test","prompt","--model",hm.MODEL,"--no-stream","--no-log"])
            self.assertEqual(kw["input"],text.encode("utf-8"))
            self.assertFalse(kw["shell"])
            intent=json.loads((work/"proposal/intent.json").read_bytes())
            self.assertEqual((intent["tools"],intent["attachments"]),([],[]))
            with self.assertRaises(ValueError):
                hm.apply_edits("DIMENS\n1 1 1 /\n",'{"tool_calls":[]}')

    def test_placeholder_prompt_cannot_be_sent(self):
        with TemporaryDirectory() as temp:
            work=Path(temp)
            text=hm.PREVIEW_MARK
            hm.write(work/"prompt.txt",text)
            with patch.object(hm.subprocess,"run",side_effect=AssertionError("no dispatch")):
                with self.assertRaises(ValueError):
                    hm.collect_proposal(work,{"prompt_sha256":hm.sha(text.encode())})

    def test_binary_reader_multiple_blocks_and_damaged_trailer(self):
        for endian in ("<",">"):
            def rec(b):
                n=struct.pack(endian+"i",len(b))
                return n+b+n
            data=rec(b"PARAMS  "+struct.pack(endian+"i",3)+b"REAL")
            data+=rec(struct.pack(endian+"f",1.5))+rec(struct.pack(endian+"2f",2.5,3.0))
            with TemporaryDirectory() as t:
                p=Path(t)/"unit.UNSMRY"
                p.write_bytes(data)
                self.assertEqual(list(hm.ecl_records(p)),[("PARAMS","REAL",(1.5,2.5,3.))])
                p.write_bytes(data[:-1])
                with self.assertRaises(ValueError): list(hm.ecl_records(p))

    def test_source_history_uses_the_deck_schedule(self):
        from datetime import date
        first=date(1967,1,1);second=date(1967,2,1);third=date(1967,3,1)
        records="".join(f"'{w}' 1* LRAT 90 10 1* /\n" for w in hm.WELLS)
        deck="SCHEDULE\nWCONHIST\n"+records+"/\nDATES\n1 FEB 1967 /\n/\nWELOPEN\n'PRO-1' SHUT /\n/\nDATES\n1 MAR 1967 /\n/\nEND\n"
        obs=hm.schedule_targets(deck,[first,second,third])
        self.assertEqual(len(obs),14)
        self.assertIn(("PRO-1",first,90.,10.),obs)
        self.assertIn(("PRO-1",second,0.,0.),obs)
        self.assertIn(("PRO-20",second,90.,10.),obs)


if __name__=="__main__":
    unittest.main()
