import torch
import numpy as np
import os
from torch.utils.data import DataLoader, Dataset
import yaml


class ImageDataset(Dataset):
    def __init__(self, inputs, outputs):
        self.inputs = inputs
        self.outputs = outputs


    def __len__(self):
        return len(self.inputs)

    def __getitem__(self, idx):
        # Load input image and target from the dataframe
        input_image = self.inputs[idx]
        target_image = self.outputs[idx]
        
        # Convert to float and apply any transformations (like normalization)
        input_image = torch.tensor(input_image, dtype=torch.float32).unsqueeze(0)
        target_image = torch.tensor(target_image, dtype=torch.float32).unsqueeze(0)

        input_image = (input_image - input_image.mean()) / input_image.std()


        return input_image, target_image

class FileDataset(Dataset):
    def __init__(self, dataset_dir_path, input_filelist, target_filelist, scale=1e-6):
        self.dataset_dir_path = dataset_dir_path
        self.input_filelist = input_filelist
        self.target_filelist = target_filelist
        self.scale = scale

    def __len__(self):
        return len(self.input_filelist)

    def __getitem__(self, idx):
        # Load input image and target from the dataframe
        input_image = np.load(self.dataset_dir_path+'/inputs/' + self.input_filelist[idx])
        target_image = np.load(self.dataset_dir_path+'/targets/' +self.target_filelist[idx])
        
        # Convert to float and apply any transformations (like normalization)
        input_image = torch.tensor(input_image, dtype=torch.float32).unsqueeze(0)
        target_image = torch.tensor(np.arcsinh(target_image / self.scale), dtype=torch.float32).unsqueeze(0)

        input_image = (input_image - input_image.mean()) / input_image.std()


        return input_image, target_image


def read_yaml_file(file_path):
    with open(file_path, 'r') as file:
        conf = yaml.safe_load(file)
    return conf


def make_diverse_dataset(env, size, num_scale=6, min_scale=1e-9, max_scale=1e-8):
    """Creates a pandas DataFrame with wavefront sensor measurements
    and corresponding mirror shapes, generated from normally distributed
    dm coefficients."""

    dm_commands = np.zeros((size*num_scale, *env.dm.coefs.shape))
    wfs_frames = np.zeros((size*num_scale, *env.wfs.cam.frame.shape))

    frame = 0

    scaling = np.linspace(min_scale, max_scale, num_scale)


    for i in range(num_scale):
        for j in range(size):

            env.tel.resetOPD()

            command = np.random.randn(*env.dm.coefs.shape) * scaling[i]

            env.dm.coefs = command.copy()

            print(np.max(np.abs(env.dm.coefs.copy())))

            env.tel*env.dm
            env.tel*env.wfs

            wfs_frames[frame] = np.float32(env.wfs.cam.frame.copy())
            dm_commands[frame] = np.float32(command.copy())

            frame += 1

            if j+1 == size:
                print(f'scale factor:{scaling[i]}')
                print(f"Generated {frame} samples")

    return wfs_frames, dm_commands


def dataset_to_file(env, size, scaling=1e-6, dir_path = '', tag = ''):
    """Creates a pandas DataFrame with wavefront sensor measurements
    and corresponding mirror shapes, generated from normally distributed
    dm coefficients."""

    os.makedirs(dir_path + '/' + tag + '/inputs', exist_ok=True)
    os.makedirs(dir_path + '/' + tag + '/targets', exist_ok=True)

    frame = 0


    for j in range(size):

        env.tel.resetOPD()

        command = np.random.randn(*env.dm.coefs.shape) * scaling

        env.dm.coefs = command.copy()

        env.tel*env.dm
        env.tel*env.wfs

        np.save(dir_path + '/' + tag + f'/inputs/wfs_' + str(int(frame)).zfill(6), np.float32(env.wfs.cam.frame.copy()))
        np.save(dir_path + '/' + tag + f'/targets/dmc_' + str(int(frame)).zfill(6), np.float32(command.copy()))

        frame += 1

        if j+1 == size:
            print(f'scale factor:{scaling[i]}')
            print(f"Generated {frame} samples")

    return




###### Junk Yard ######

# def get_OL_phase_dataset(env, size):
#     """Creates a pandas DataFrame with wavefront sensor measurements
#     and corresponding mirror shapes."""

#     # Create random OPD maps
#     tel_res = env.dm.resolution

#     true_phase = np.zeros((tel_res,tel_res,size))

#     dataset = pd.DataFrame(columns=['wfs', 'dm'])

#     seeds = np.random.randint(1, 10000, size=size)

#     for i in range(size):
#         env.atm.generateNewPhaseScreen(seeds[i])
#         env.tel*env.wfs

#         dataset.loc[i] = {'wfs': np.array(env.wfs.cam.frame.copy()), 'dm': np.array(env.OPD_on_dm())}
#         true_phase[:,:,i] = env.tel.OPD

#         if i % 100 == 0:
#             print(f"Generated {i} open loop samples")


#     return true_phase, dataset

# def get_CL_phase_dataset(env, size, reconstructor):
#     """Creates a pandas DataFrame with wavefront sensor measurements
#     and corresponding mirror shapes, using the closed loop system."""

#     recontructor.eval()

#     # Create random OPD maps

#     tel_res = env.dm.resolution

#     true_phase = np.zeros((tel_res,tel_res,size))

#     dataset = pd.DataFrame(columns=['wfs', 'dm'])

#     seeds = np.random.randint(1, 10000, size=size)

#     for i in range(size):
#         env.atm.generateNewPhaseScreen(seeds[i])
#         env.tel*env.wfs

#         obs = torch.tensor(env.wfs.cam.frame).clone().detach().float().unsqueeze(0).unsqueeze(0)

#         with torch.no_grad(): 
#             action = reconstructor(obs).squeeze(0).squeeze(0) #env.integrator()

#         pred_OPD = OPD_model(action, env.dm.modes, env.dm.resolution, env.xvalid, env.yvalid)

#         residual_phase = env.tel.OPD.copy() - pred_OPD.squeeze().numpy()

#         env.tel.OPD = residual_phase
#         env.tel*env.wfs

#         dataset.loc[i] = {'wfs': np.array(env.wfs.cam.frame.copy()), 'dm': np.array(env.OPD_on_dm())}
#         true_phase[:,:,i] = env.tel.OPD

#         if i % 100 == 0:
#             print(f"Generated {i} closed loop samples")

#     return true_phase, dataset