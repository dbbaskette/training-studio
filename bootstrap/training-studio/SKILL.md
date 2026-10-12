---
name: training-studio
description: Turn a topic into researched training in the current directory, with a research report, teaching blueprint, learner guide, product or competitive brief, slide deck and practice scenarios, at one or more levels from 101 to 401, with optional Yoodli scenarios. Use to build, resume, check or revise a training, lesson or course.
---

# Training Studio

This entry finds the guidance for the training in the current directory. Guidance is kept up to date separately from the installed scripts, and each training stays on the guidance it started with.

1. From the directory the harness was launched in, run this, where `<skill>` is this skill's directory:

   ```sh
   python3 "<skill>/scripts/sync_guidance.py" start
   ```

2. It prints JSON. If there is an `error`, show it and stop; do not improvise guidance. If there is a `notice`, tell the user once.
3. Read the file named by `entry` and follow it. Its links are relative to that file. Wherever guidance says `training.py`, run `python3` with the path given as `helper`.

Only when the user asks to move a training to newer guidance: run the same script with `update`, then run the checks again, since their results can differ.
