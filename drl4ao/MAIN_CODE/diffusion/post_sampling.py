#%%
import torch
from torch.func import grad, vmap
import numpy as np
import os, sys
import matplotlib.pyplot as plt
from score_models import ScoreModel, NCSNpp

# %%
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

script_dir = os.path.dirname(os.path.abspath(__file__))
# Print the size in mb of the dataset file
lr = np.load(f'{script_dir}/images/thesis_data/lr.npy')
hr = np.load(f'{script_dir}/images/thesis_data/hr.npy')

num_modes = 30

zernike_modes = np.load(f'{script_dir}/masks_and_transforms/m2c_wfs_pupil_95modes.npy')[:,:num_modes]
mode_decomp = np.linalg.pinv(zernike_modes)
wfs_pupil_mask = np.load(f'{script_dir}/masks_and_transforms/wfs_pupil_mask.npy')
padded_pupil_mask = np.pad(wfs_pupil_mask, pad_width=1, mode='constant', constant_values=0)
xvalid, yvalid = np.where(padded_pupil_mask == 1)


model = ScoreModel(checkpoints_directory=f'{script_dir}/datasets/cp_unconditional/', device=device)

B = 1000
channels = 4


# %%
num_steps = 1000
dt = -1/num_steps #reverse time

s_min = model.sde.sigma_min
s_max = model.sde.sigma_max

aa_T = torch.from_numpy(mode_decomp @ zernike_modes).to(device=device, dtype=torch.float32)
aa_block = torch.kron(torch.eye(4).to(device), aa_T)


def log_likelihood(x_t, eta, sig_t, aa_T, mode_decomp, xvalid, yvalid, y, noise_scale):

    Sigma_t = eta**2 * torch.eye(len(zernike_modes[0])).to(device) + aa_T * sig_t[0].squeeze()**2 / noise_scale
    Sigma_t_inv = torch.inverse(Sigma_t)
    Sigma_t_inv = Sigma_t_inv.clone().contiguous().to(device)
    Sigma_t_inv_block = torch.kron(torch.eye(4).to(device), Sigma_t_inv).to(device=device)

    Ax_t = torch.einsum('mn,cn->cm', mode_decomp, x_t[:,xvalid, yvalid])

    diff = (y - Ax_t).reshape(-1)

    S_into = Sigma_t_inv_block @ (y - Ax_t).reshape(-1).unsqueeze(-1)

    return -0.5 *torch.dot(diff, S_into.squeeze())
     

for noise_scale in np.linspace(1, 100, 10):
    with torch.no_grad():
        # for eta in np.logspace(1, 2.2, 10):
        eta = 0.

        lr = torch.tensor(lr, dtype=torch.float32, device=device)

        mode_decomp = torch.tensor(mode_decomp, dtype=torch.float32, device=device)
        y_modes = torch.einsum('mn,bcn->bcm', mode_decomp, lr[:B,:,xvalid, yvalid])
        y = y_modes.to(device)

        # x_t = torch.normal(0, s_max, (B, channels, 24, 24)).to(device)
        x_t = torch.tensor(lr[:B]).to(device)
        # t_start = np.log(np.std(lr[0][0] - hr[0][0])) / np.log(s_max / s_min)
        t_start = 1.

        for i, t in enumerate(np.linspace(t_start, 0, num_steps)):
            print(f'Step {i}/{num_steps}')

            t = torch.tensor(t).to(device) * torch.ones(B).to(device)
            z = torch.randn_like(x_t).to(device)
            dw = abs(dt)**(1/2) * z
            g = model.sde.diffusion(t, x_t)

            sig_t = model.sde.sigma(t).unsqueeze(1).unsqueeze(2).unsqueeze(3)
            
            score_likelihood = vmap(grad(log_likelihood, argnums=(0,)), in_dims=(0, None, 0, None, None, None, None, 0, None))(x_t, eta, sig_t, aa_T, mode_decomp, xvalid, yvalid, y, noise_scale)

            score_likelihood = score_likelihood[0]

            score_prior = model.score(t, x_t)

            dx = - g**2 * (score_likelihood + score_prior) * dt + g * dw
            # dx = - g**2 * (score_prior) * dt + g * dw

            x_t += dx

        

        lr_fft2 = np.fft.fft2(lr.detach().cpu().sum(axis=1))
        lr_fft_shifted = np.fft.fftshift(lr_fft2, axes=(-2, -1))

        hr_fft2 = np.fft.fft2(hr.sum(axis=1))
        hr_fft_shifted = np.fft.fftshift(hr_fft2, axes=(-2, -1))


        sam_fft2 = np.fft.fft2(x_t.detach().cpu().sum(dim=1))
        sam_fft_shifted = np.fft.fftshift(sam_fft2, axes=(-2, -1))


        def distance_matrix(n, c_row, c_col):
                # Create a grid of indices
                i, j = np.indices((n, n))
                
                # Calculate the distance for each pixel
                distances = np.sqrt((i - c_row)**2 + (j - c_col)**2)
                
                return distances

        n = 24

        i_c, j_c = n // 2, n // 2

        r = distance_matrix(n, i_c, j_c)

        max_radius = n // 2
        mesh = np.linspace(0, max_radius, max_radius*2)

        # Compute power spectrum for each batch
        batch_pow_lr = []
        batch_pow_hr = []
        batch_pow_sam = []

        for b in range(B):
            pow_lr = []
            pow_hr = []
            pow_sam = []
            for i in range(len(mesh) - 1):
                # Create a mask for the current radial bin
                mask = (mesh[i] <= r) & (r < mesh[i + 1])
                if np.any(mask):  # Avoid issues with empty bins
                    pow_lr.append(np.mean(np.abs(lr_fft_shifted[b][mask])))
                    pow_hr.append(np.mean(np.abs(hr_fft_shifted[b][mask])))
                    pow_sam.append(np.mean(np.abs(sam_fft_shifted[b][mask])))
                else:
                    pow_lr.append(0)  # Handle empty bins gracefully
                    pow_hr.append(0)
                    pow_sam.append(0)
            batch_pow_lr.append(pow_lr)
            batch_pow_hr.append(pow_hr)
            batch_pow_sam.append(pow_sam)

        # Convert results to a numpy array for further analysis
        batch_pow_lr = np.array(batch_pow_lr)
        batch_pow_hr = np.array(batch_pow_hr)
        batch_pow_sam = np.array(batch_pow_sam)
        
        figure = plt.figure()
        plt.plot(np.mean(batch_pow_lr, axis=0), label="LR")
        plt.plot(np.mean(batch_pow_hr, axis=0), label="HR")
        plt.plot(np.mean(batch_pow_sam, axis=0), label="Sampled")
        plt.yscale('log')
        plt.legend()
        plt.title(f't_start = {t_start:.2f}, noise scale = {noise_scale}, num_modes = {len(zernike_modes[0])}')
        # plt.title(f'Basically prior sampling')

        plt.savefig(f'{script_dir}/images/powerspectrum_noise_scale_{noise_scale:.0f}_t_start_{t_start:.2f}.png')
        plt.show()

        # np.save(f'{script_dir}/images/batch_pow_lr_{eta:.0f}.npy', batch_pow_lr)
        # np.save(f'{script_dir}/images/batch_pow_hr_{eta:.0f}.npy', batch_pow_hr)
        # np.save(f'{script_dir}/images/batch_pow_sam_{eta:.0f}.npy', batch_pow_sam)

        fig2 = plt.figure()
        x_t_modes = np.einsum('mn,bcn->bcm', mode_decomp.detach().cpu(), x_t.detach().cpu()[:,:,xvalid, yvalid])
        lr_modes = np.einsum('mn,bcn->bcm', mode_decomp.detach().cpu(), lr.detach().cpu()[:,:,xvalid, yvalid])
        hr_modes = np.einsum('mn,bcn->bcm', mode_decomp.detach().cpu(), hr[:,:,xvalid, yvalid])

        # Compute power spectra per image and pupil
        P_x_t = x_t_modes**2
        P_lr = lr_modes**2
        P_hr = hr_modes**2

        # Compute deviation per image and pupil
        D_x_t = np.abs(P_x_t - P_lr) / P_lr
        D_hr = np.abs(P_hr - P_lr) / P_lr

        # Compute mean deviation across batch and pupils
        mean_D_x_t = np.mean(D_x_t, axis=(0, 1))  # Averaged over batch and pupils
        mean_D_hr = np.mean(D_hr, axis=(0, 1))  # Averaged over batch and pupils
        std_D_hr = np.std(D_hr, axis=(0, 1))  # Standard deviation of HR deviation

        # Compute 1-sigma and 2-sigma regions
        hr_1sigma_upper = mean_D_hr + std_D_hr
        hr_1sigma_lower = mean_D_hr - std_D_hr
        hr_2sigma_upper = mean_D_hr + 2 * std_D_hr
        hr_2sigma_lower = mean_D_hr - 2 * std_D_hr

        # Plot deviations
        plt.figure(figsize=(8, 5))
        plt.plot(mean_D_x_t, label="Mean Deviation of x_t from lr", c="k")
        plt.plot(mean_D_hr, label="Mean Deviation of hr from lr", c="b")

        # Fill regions for 1σ and 2σ around hr deviation
        plt.fill_between(range(num_modes), hr_1sigma_lower, hr_1sigma_upper, color='b', alpha=0.3, label="1σ HR Deviation")
        plt.fill_between(range(num_modes), hr_2sigma_lower, hr_2sigma_upper, color='b', alpha=0.15, label="2σ HR Deviation")

        plt.xlabel("Mode index")
        plt.ylabel("Mean Relative Power Deviation")
        plt.legend()
        plt.title(f"Mean Modal Deviation - noise scale = {noise_scale:.0f}, t_start = {t_start:.2f}")
        plt.yscale('log')
        plt.savefig(f'{script_dir}/images/mean_deviation_noise_scale_{noise_scale:.0f}_t_start_{t_start:.2f}.png')
        plt.show()

    # torch.save(x_t, f'{script_dir}/images/samples_unc.pt')
# %%
fig, ax = plt.subplots(3, 4)

for i in range(4):
    ax[0, i].imshow(lr.detach().cpu()[0][i])
    ax[0, i].axis('off')
    ax[0, i].set_title(f"Pupil {i+1}")
    ax[1, i].imshow(hr[0][i])
    ax[1, i].axis('off')
    ax[2, i].imshow(x_t.detach().cpu()[0][i])
    ax[2, i].axis('off')

row_labels = ["Low-Resolution (LR)", "High-Resolution (HR)", "Diffused Sample (x_t)"]


for row in range(3):
    ax[row, 0].annotate(row_labels[row], xy=(-0.5, 0.5), xycoords="axes fraction",
                         va='center', ha='right', fontsize=12, fontweight='bold',
                         rotation=0)

plt.savefig(f'{script_dir}/images/example_sample.png')
plt.show()