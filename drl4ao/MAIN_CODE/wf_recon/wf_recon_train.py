#%%
import os,sys
import torch
import torch.optim as optim
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
import numpy as np

from ML_stuff.dataset_tools import ImageDataset, FileDataset, make_diverse_dataset, read_yaml_file, data_from_stats
from ML_stuff.models import Unet_big, create_edge_weight_matrix
from Plots.plots import save_plots
from types import SimpleNamespace
import matplotlib.pyplot as plt
plt.rcParams['image.cmap'] = 'inferno'
# SimpleNamespace takes a dict and allows the use of
# keys as attributes. ex: args['r0'] -> args.r0
#For Razor sim
# from PO4AO.mbrl_funcsRAZOR import get_env
# try:
#     args = SimpleNamespace(**read_yaml_file('./Conf/razor_config_po4ao.yaml'))
# except:
#     args = SimpleNamespace(**read_yaml_file('../Conf/razor_config_po4ao.yaml'))

# For papyrus sim
from PO4AO.mbrl import get_env
try:
    args = SimpleNamespace(**read_yaml_file('./Conf/papyrus_config.yaml'))
except:
    args = SimpleNamespace(**read_yaml_file('../Conf/papyrus_config.yaml'))

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

savedir = os.path.dirname(__file__)


env = get_env(args)


with open("thesis_augmented2.txt", "a") as f:
    f.write(f"Done making env \n")


# %%

#------------- Uncomment to make your own dataset locally -------------#

# # Generate the dataset of wfs images and phase maps
# env.tel.resetOPD()
# env.tel*env.dm*env.wfs
# wfsf, dmc = make_diverse_dataset(env, size=20000, num_scale=1,\
#                      min_scale=1e-6, max_scale=1e-6, savedir=savedir+'/datasets', tag='big_boy')

# # X = wfsf
# # y_raw = dmc

# ds_size = len(X)

# # Save the dataset
# np.save(savedir+'/datasets/wfs_frames_bigboy', wfsf)
# np.save(savedir+'/datasets/dm_cmds_bigboy', dmc)


#------------- Uncomment to load a dataset from a single file -------------#
# X = np.load(savedir+'/datasets/wfs_frames_emin6.npy')
# y_raw = np.load(savedir+'/datasets/dm_cmds_emin6.npy')

# #Transform commands to regular scale
# y = np.arcsinh(y_raw / 1e-6)

# ds_size = len(X)
#------------- Uncomment to load a dataset from individual files -------------#

data_dir_path = '/home/parker09/projects/def-lplevass/parker09/RLAO/drl4ao/MAIN_CODE/wf_recon/datsets/thesis_data'

# X = os.listdir(data_dir_path + '/inputs')
# y = os.listdir(data_dir_path + '/targets')

ds_size = 400000


# %%
# Set the random seed for reproducibility
np.random.seed(43257458)

# Shuffle the data indices
indices = np.arange(ds_size)
np.random.shuffle(indices)

# Define the split ratios
train_ratio = 0.8
val_ratio = 0.1
test_ratio = 0.1

# Calculate the split indices
train_size = int(train_ratio * ds_size)
val_size = int(val_ratio * ds_size)

# Get the corresponding indices for each set
train_indices = indices[:train_size]
val_indices = indices[train_size:train_size + val_size]
test_indices = indices[train_size + val_size:]


# Split the data
# X_train, X_val, X_test = X[train_indices], X[val_indices], X[test_indices]
# y_train, y_val, y_test = y[train_indices], y[val_indices], y[test_indices]

# Now you have:
# X_train, y_train: training set
# X_val, y_val: validation set
# X_test, y_test: test set

#------------- Uncomment files loaded in memory -------------#
# D_train = ImageDataset(X_train, y_train)
# D_test = ImageDataset(X_test, y_test)
# D_val = ImageDataset(X_val, y_val)


#------------- Uncomment for datasets from file names -------------#
input_file_path = data_dir_path+'/wfs_frames_augmented.npy'
target_file_path = data_dir_path+'/dm_cmds.npy'

dm_shape = env.dm.coefs.shape
wfs_shape=env.wfs.cam.frame.shape

D_train = FileDataset(input_file_path, target_file_path, train_indices, dm_shape=dm_shape, wfs_shape=wfs_shape, size=ds_size)
D_test = FileDataset(input_file_path, target_file_path, test_indices, dm_shape=dm_shape, wfs_shape=wfs_shape, size=ds_size)
D_val = FileDataset(input_file_path, target_file_path, val_indices, dm_shape=dm_shape, wfs_shape=wfs_shape, size=ds_size)

with open("thesis_augmented2.txt", "a") as f:  # 'a' mode appends to the file
    f.write(f"Done making train, test, val datasets \n")

# %%

# checkpoint = torch.load(savedir+'/models/useable/unmod.pt',map_location=device)


# Make sure to use the correct network before loading the state dict
reconstructor = Unet_big(env.xvalid,env.yvalid)
# Restore the regular model and optimizer state
# reconstructor.load_state_dict(checkpoint['model_state_dict'])

# reconstructor = Unet_big(env.xvalid, env.yvalid)
reconstructor = reconstructor.to(device)

# EMA of model parameters
# ema_reconstructor = torch.optim.swa_utils.AveragedModel(reconstructor, \
#     multi_avg_fn=torch.optim.swa_utils.get_ema_multi_avg_fn(0.999))

# optimizer = optim.Adam(reconstructor.parameters(), lr=0.0001)
optimizer = optim.Adam(reconstructor.parameters(), lr=0.00001)
criterion = nn.MSELoss()

reconstructor.to(device)
# ema_reconstructor.to(device)


train_loader = DataLoader(D_train, batch_size=64, shuffle=True)
val_loader = DataLoader(D_val, batch_size=64, shuffle=True)
test_loader = DataLoader(D_test, batch_size=64, shuffle=False)


train_losses = []
val_losses = []
ema_val_losses = []
# Variable to store the best validation loss and path to save the model
best_val_loss = float('inf')  # Initialize to infinity
save_path = savedir+'/models/thesis_models/augmented2.pt'  # Path to save the best model


# Parameters
batch_size, channels, height, width = 64, 1, 21, 21
center = [10,10]  # Assuming the circle is centered
radius = 10.5  # Adjust radius as needed
sigma = 10  # Controls the spread of the weights around the boundary

# Create the edge weight matrix
weight_matrix = create_edge_weight_matrix(height, width, center, radius, sigma)

# Expand the weight matrix to match the dimensions of elementwise_loss
weight_matrix = weight_matrix.unsqueeze(0).unsqueeze(0)  # Shape: [1, 1, height, width]
# weight_matrix = weight_matrix.expand(batch_size, channels, height, width)


with open("thesis_augmented2.txt", "a") as f:  # 'a' mode appends to the file
    f.write(f"Starting Training \n")



n_epochs = 300
for epoch in range(n_epochs):

    start = time.time()

    #Training phase
    reconstructor.train()
    running_loss = 0.0
    for inputs, targets in train_loader:
        # Zero the parameter gradients
        optimizer.zero_grad()
        inputs = inputs.to(device)
        targets = targets.to(device)
        
        # Forward pass
        outputs = env.img_to_vec(reconstructor(inputs))

        # Get the OPD from the model
        # loss = criterion(outputs, targets)

        elementwise_loss = F.mse_loss(outputs, targets, reduction='none') 

        # Apply the weight matrix
        weighted_loss = elementwise_loss * env.img_to_vec(weight_matrix)
        # Compute the mean of the weighted loss
        loss = weighted_loss.mean()

        
        # Backward pass and optimization
        loss.backward()
        optimizer.step()
        # ema_reconstructor.update_parameters(reconstructor)

        running_loss += loss.item()

    
    avg_train_loss = running_loss/len(train_loader)
    train_losses.append(avg_train_loss)
    print(f"Epoch {epoch+1}/{n_epochs}, Loss: {avg_train_loss}")

    end_tr = time.time()

    with open("thesis_augmented2.txt", "a") as f:  # 'a' mode appends to the file
        f.write(f"One training epoch took {end_tr - start} seconds\n")



    # Validation phase
    reconstructor.eval()
    val_loss = 0.0
    ema_val_loss = 0.0
    with torch.no_grad():
        for inputs, targets in val_loader:
            inputs = inputs.to(device)
            targets = targets.to(device)

            #forward pass
            outputs = env.img_to_vec(reconstructor(inputs))
            # ema_outputs = env.img_to_vec(ema_reconstructor(inputs))


            # loss = criterion(outputs, targets)

            elementwise_loss = F.mse_loss(outputs, targets, reduction='none') 

            # Apply the weight matrix
            weighted_loss = elementwise_loss * env.img_to_vec(weight_matrix)
            # Compute the mean of the weighted loss
            loss = weighted_loss.mean()

            val_loss += loss.item()

            # ema_loss = criterion(ema_outputs, targets)
            # ema_val_loss += ema_loss.item()

    avg_val_loss = val_loss/len(val_loader)
    val_losses.append(avg_val_loss)

    # avg_ema_val_loss = ema_val_loss/len(val_loader)
    # ema_val_losses.append(avg_ema_val_loss)

    with open("thesis_augmented2.txt", "a") as f:  # 'a' mode appends to the file
        f.write(f"One validation epoch took {time.time() - end_tr} seconds\n")


    if avg_val_loss < best_val_loss:
        best_val_loss = avg_val_loss  # Update the best validation loss
        print(f"Validation loss improved to {avg_val_loss:.4f}, saving model...")
        
        # Save the best model
        torch.save({
            'epoch': epoch + 1,
            'model_state_dict': reconstructor.state_dict(),
            # 'ema_model_state_dict': ema_reconstructor.module.state_dict(),
            'optimizer_state_dict': optimizer.state_dict(),
            'val_loss': best_val_loss,
        }, save_path)

    with open("thesis_augmented2.txt", "a") as f:  # 'a' mode appends to the file
        f.write(f"Epoch {epoch + 1}/{n_epochs}, Loss: {avg_val_loss}\n")

    print(f'Epoch {epoch+1}/{n_epochs}, Validation Loss: {avg_val_loss}')

    np.save(savedir+'/losses/train_loss_thesis_augmented2_atm', train_losses)
    np.save(savedir+'/losses/val_loss_thesis_augmented2_atm', val_losses)


# Test phase (after all epochs)
reconstructor.eval()  # Set the model to evaluation mode
test_loss = 0.0
with torch.no_grad():
    for inputs, targets in test_loader:
        inputs = inputs.to(device)
        targets = targets.to(device)

        # Forward pass
        outputs = env.img_to_vec(reconstructor(inputs))

        # Compute loss
        loss = criterion(outputs, targets)

        test_loss += loss.item()

# Calculate average test loss
avg_test_loss = test_loss / len(test_loader)
print(f"Test Loss: {avg_test_loss}")


# np.save(savedir+'/losses/ema_val_loss_papyrus_unet_big_200k', ema_val_losses)
# torch.save(reconstructor.state_dict(), savedir+'/models/last_papyrus_unet_big_200k.pt')

# %%
