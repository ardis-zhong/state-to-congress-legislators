#!/bin/bash
# Run the Table 6 fine-tuning runs one after another on one GPU (TIDE JupyterHub terminal, or any GPU machine).
# From the repo root:
#   bash replication/scripts/topics/run_all_topics.sh check               # smoke test on this GPU (a few minutes)
#   bash replication/scripts/topics/run_all_topics.sh size_n1000_s1       # one run, to see how long runs take
#   nohup bash replication/scripts/topics/run_all_topics.sh all > topic_runs.log 2>&1 &    # everything, in order
#   tail topic_runs.log                                                   # progress
# Finished runs are skipped, so "all" can be started again after an interruption (an interrupted run starts over).
set -u
RUNS=replication/data/reference/topic_runs.csv
FT=replication/scripts/topics/finetune_topics.py
for f in "$RUNS" "$FT" topics_data/federal_topic_data.csv.gz topics_data/state_topic_data.csv.gz; do
  [ -f "$f" ] || { echo "Missing $f (run from the repo root; upload the two .csv.gz files into topics_data/)"; exit 1; }
done
nvidia-smi -L || { echo "No NVIDIA GPU here: restart the server with 1 GPU selected"; exit 1; }
WHAT="${1:-}"
[ -n "$WHAT" ] || { echo "Say what to run: check, all, or a run_id from $RUNS"; exit 1; }

finished() {
  local d="topic_runs_out/$1"
  [ -f "$d/metrics.json" ] || return 1
  grep -q '"train_from": "101"' "$d/metrics.json" || return 1       # made before the 1989-on design: run again
  if [ "$1" = "size_all_s1" ] && [ ! -f "$d/model/tokenizer_config.json" ]; then return 1; fi
  return 0
}
run() {
  if finished "$1"; then echo "skip $1 (finished)"; return 0; fi
  echo "=== $1  $(date)"
  if [ "$1" = "size_all_s1" ]; then python3 -u "$FT" --run-id "$1" --save-model    # the model that labels Table 6
  else python3 -u "$FT" --run-id "$1"; fi
}

case "$WHAT" in
  check) python3 -u "$FT" --run-id size_n1000_s1 --smoke --out topic_smoke_out ;;
  all)
    failed=""
    for id in $(tail -n +2 "$RUNS" | cut -d, -f1); do run "$id" || failed="$failed $id"; done
    echo "Done $(date). Failed:${failed:- none}"
    [ -z "$failed" ] ;;
  *)
    grep -q "^$WHAT," "$RUNS" || { echo "$WHAT is not a run_id in $RUNS"; exit 1; }
    run "$WHAT" ;;
esac
