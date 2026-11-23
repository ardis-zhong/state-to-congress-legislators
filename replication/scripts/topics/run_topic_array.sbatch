#!/bin/bash
# SLURM job array for the Table 6 runs: one array task per row of topic_runs.csv (26 runs -> --array=1-26).
# Adjust the partition/account lines to what SDSU research computing tells you; the rest should not need changes.
#SBATCH --job-name=table6-topics
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --array=1-26
#SBATCH --output=topic_logs/%x_%a.out
##SBATCH --partition=gpu
##SBATCH --account=CHANGE_ME

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"                      # submit from the repo root
mkdir -p topic_logs
RUN_ID=$(awk -F, -v n="$((SLURM_ARRAY_TASK_ID + 1))" 'NR==n {print $1}' replication/data/reference/topic_runs.csv)
EXTRA=""
[ "$RUN_ID" = "size_all_s1" ] && EXTRA="--save-model"   # the model that labels Table 6
echo "task ${SLURM_ARRAY_TASK_ID}: ${RUN_ID}"
python3 replication/scripts/topics/finetune_topics.py --run-id "$RUN_ID" $EXTRA
