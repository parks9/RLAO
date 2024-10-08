#!/bin/bash
#SBATCH --tasks=1
#SBATCH --cpus-per-task=2 # maximum cpu per task is 3.5 per gpus
#SBATCH --gres=gpu:1
#SBATCH --mem=40G                        # memory per node
#SBATCH --time=00-03:59         # time (DD-HH:MM)
#SBATCH --account=def-lplevass
#SBATCH --job-name=unet_and_int
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=parker.levesque@gmail.com

cd MAIN_CODE

source $HOME/projects/def-lplevass/parker09/drl4ao_env/bin/activate
python $HOME/projects/def-lplevass/parker09/RLAO/drl4ao/MAIN_CODE/integrator_network.py
