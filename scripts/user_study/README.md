# Time-to-root-cause user study (Table F)

Measures the human-centred benefit of the explainable alert view (note 14).

**Design.** 6–10 participants (classmates), 3 incidents each, within-subject: every participant
does some incidents with **A — raw logs + terminal** (`grep`, `less`, any text editor) and some with
**B — our alert view**. Starting condition alternates between participants; incident order is
random. Individual skill therefore cancels out.

**Task.** "Name the faulty service and the step that is failing." The facilitator starts a timer
when the material is opened and stops it when the participant gives a final answer.

## Steps

1. Build the kit from recorded test runs:
   `python scripts/user_study/make_packs.py --runs test_s4 test_s5 --participants 8`
2. Print or share `reports/user_study/assignment.csv`; keep `answer_key.csv` away from participants.
3. Give each participant only the file listed in `material`. For condition B you may also open the
   dashboard's Investigate tab on the same run (sidebar → run) instead of the markdown file.
4. Fill `responses_template.csv` (save as `responses.csv`): `start_time`, `end_time` (HH:MM:SS),
   `answer_service`, and `answer_step` = `y` if the described step matches the key, else `n`.
5. `python scripts/user_study/analyze.py reports/user_study/responses.csv` → Table F rows
   (`exp_id = USER` in `reports/results.csv`), with a paired Wilcoxon test when n ≥ 5.

Brief participants on the system (2 min, same script for everyone) before the first incident.
Report the numbers whatever they show.
