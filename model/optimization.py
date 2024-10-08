"""
Description:
    Contains the optimization routine for the ULSDPB model.

Functions:
    routine: the optimization routine
    iteration: a single iteration of the optimization routine
"""

# Standard library modules
import cProfile
import csv
import os
import time

# External modules
import numpy as np

# Own modules
import model.elbo
import model.functions
import model.state


def routine(
        q,
        data,
        prior,
        is_fixed,
        fixed_values,
        M,
        model_output_folder,
        n_iter,
        n_save_per,
        misc_settings,
        vi_settings,
):
    # this code snippet prints the names of the fixed parameters
    if any(is_fixed):
        print('Fixed parameters:')
        [
            print(parameter) for (parameter, is_fixed)
            in is_fixed._asdict().items() if is_fixed
        ]

    elbo_start_routine = model.elbo.compute_elbo_container(
        q=q,
        M=M,
        n_purchases_per_basket=data.dim_n,
        total_customers=data.total_customers,
        total_baskets=data.total_baskets,
    )

    # Prints the initial ELBO value
    print('ELBO before optimization:')
    print(elbo_start_routine, end='\n\n')

    # Create a CSV file to store ELBO values
    elbo_file = os.path.join(
        model_output_folder,
        'elbo.csv'
    )

    with open(elbo_file, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(elbo_start_routine._fields)

    elbo_dict = {}
    elbo_current = elbo_start_routine

    # Container for the variational parameters of q(z_ibn)
    theta_q_z = np.empty((data.total_purchases, M))

    tallies = {
        'updated_mu_q': np.zeros(data.total_baskets, dtype=int),
        'updated_sigma_sq_q': np.zeros(data.total_baskets, dtype=int),
        'updated_both': np.zeros(data.total_baskets, dtype=int),
    }

    # Profiling code
    pr = None
    if misc_settings.profile_code:
        pr = cProfile.Profile()
        pr.enable()

    start_time = time.time()

    for n in range(n_iter):
        # Check if the current iteration needs to be saved
        save_this_iteration = ((n + 1) % n_save_per) == 0
        is_last_iteration = (n == (n_iter - 1))
        print_this_iteration = (n % misc_settings.n_print_per) == 0

        # Reset tallies for q(alpha) updates
        tallies['updated_both'][:] = 0
        tallies['updated_mu_q'][:] = 0
        tallies['updated_sigma_sq_q'][:] = 0

        # Check the consistency of the variational state
        if misc_settings.check_state_consistency:
            model.state.check_state(
                q=q,
                data=data,
                prior=prior,
                is_fixed=is_fixed,
                fixed_values=fixed_values,
                M=M,
            )

            print('Variational state: Consistent')

        # Perform a single iteration of the optimization routine
        q = iteration(
            q=q,
            theta_q_z=theta_q_z,
            tallies=tallies,
            data=data,
            prior=prior,
            is_fixed=is_fixed,
            vi_settings=vi_settings,
            M=M,
        )

        # Check the consistency of the variational state
        if misc_settings.check_state_consistency:
            model.state.check_state(
                q=q,
                data=data,
                prior=prior,
                is_fixed=is_fixed,
                fixed_values=fixed_values,
                M=M,
            )

            print('Variational state: Consistent')

        # Compute the ELBO value after the iteration
        elbo_after_iteration = model.elbo.compute_elbo_container(
            q=q,
            M=M,
            n_purchases_per_basket=data.dim_n,
            total_customers=data.total_customers,
            total_baskets=data.total_baskets,
        )

        # Print information about the current iteration
        if print_this_iteration:
            print('\nPost iteration: ', n)
            print(elbo_after_iteration)
            print(
                'ELBO difference:',
                elbo_after_iteration.total - elbo_current.total
            )
            print('q(alpha) % of proposals accepted: ', end='')
            print(
                'mu_q_ib {:.2f}%, sigma_sq_q_ib {:.2f}%, both {:.2f}%'.format(
                    100 * np.mean(tallies['updated_mu_q'] != 0),
                    100 * np.mean(tallies['updated_sigma_sq_q'] != 0),
                    100 * np.mean(tallies['updated_both'] != 0),
                )
            )

        with open(elbo_file, 'a', newline='') as f:
            w = csv.writer(f)
            w.writerow(elbo_after_iteration)

        elbo_current = elbo_after_iteration
        elbo_dict[n] = elbo_after_iteration

        if save_this_iteration or is_last_iteration:
            np.savez_compressed(
                os.path.join(model_output_folder, 'state_{0:0>10}'.format(n)),
                **q._asdict()
            )

    if misc_settings.profile_code:
        pr.disable()
        pr.dump_stats(os.path.join(model_output_folder, 'profile_stats'))

    print('Total number of iterations:', n_iter)
    print('Time spent:', time.time() - start_time)

    return q, elbo_dict


def iteration(
        q,
        theta_q_z,
        tallies,
        data,
        prior,
        is_fixed,
        vi_settings,
        M,
):

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # LOCAL Q UPDATE  # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    # Auxiliary variables for the efficient inverse
    L_inv = np.diag(q.tau_alpha**-0.5)
    U, v, _ = np.linalg.svd(L_inv @ q.lambda_kappa @ L_inv.T)
    U_T_mmul_L_inv = U.T @ L_inv
    log_det_C = np.sum(np.log(q.tau_alpha))

    model.functions.update_q_local(
        # # variables to be updated
        # z
        theta_q_z=theta_q_z,
        ev_q_counts_basket=q.counts_basket,
        ev_q_entropy_q_z=q.entropy_q_z,
        ev_q_counts_phi=q.counts_phi,
        # alpha
        mu_q_alpha=q.mu_q_alpha,
        sigma_sq_q_alpha=q.sigma_sq_q_alpha,
        ss_mu_q=q.ss_mu_q_alpha,
        ss_log_sigma_q=q.ss_log_sigma_q_alpha,
        ev_q_alpha_sq=q.alpha_sq,
        ev_q_log_theta_denom_approx=q.log_theta_denom_approx,
        ev_q_entropy_q_alpha=q.entropy_q_alpha,
        # alpha diagnostics
        updated_mu_q=tallies['updated_mu_q'],
        updated_sigma_sq_q=tallies['updated_sigma_sq_q'],
        updated_both=tallies['updated_both'],
        # kappa
        ev_q_kappa=q.kappa,
        ev_q_kappa_sq=q.kappa_sq,
        ev_q_kappa_outer=q.kappa_outer,
        ev_q_entropy_q_kappa=q.entropy_q_kappa,
        # mix
        ev_q_eps_alpha=q.eps_alpha,
        # # rest
        ev_q_log_phi=q.log_phi,
        ev_q_tau_alpha=q.tau_alpha,
        ev_q_mu_kappa=q.mu_kappa,
        ev_q_lambda_kappa=q.lambda_kappa,
        ev_q_rho=q.rho,
        ev_q_rho_outer=q.rho_outer,
        ev_q_delta_kappa=q.delta_kappa,
        ev_q_delta_kappa_sq=q.delta_kappa_sq,
        dim_m=M,
        data=data,
        vi_settings=vi_settings,
        is_fixed=is_fixed,
        U_T_mmul_L_inv=U_T_mmul_L_inv,
        v=v,
        log_det_C=log_det_C,
    )

    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # GLOBAL Q UPDATE # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
    # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    if not is_fixed.phi:
        model.functions.update_q_phi(
            eta_q_phi=q.eta_q_phi,
            ev_q_log_phi=q.log_phi,
            negative_kl_q_p_phi=q.negative_kl_q_p_phi,
            ev_q_counts_phi=q.counts_phi,
            prior=prior,
            dim_m=M,
        )

    if not is_fixed.beta:
        model.functions.update_q_beta(
            eta_q_beta=q.eta_q_beta,
            ev_q_beta=q.beta,
            ev_q_beta_outer=q.beta_outer,
            negative_kl_q_p_beta=q.negative_kl_q_p_beta,
            ev_q_eps_alpha=q.eps_alpha,
            ev_q_tau_alpha=q.tau_alpha,
            ev_q_delta_beta=q.delta_beta,
            ev_q_delta_beta_sq=q.delta_beta_sq,
            x=data.x,
            x_outer_sum_first=data.x_outer_sum_first,
            x_outer_sum_not_first=data.x_outer_sum_not_first,
            prior=prior,
            ib_first=data.ib_first,
            ib_not_first=data.ib_not_first,
        )

    if not is_fixed.gamma:
        model.functions.update_q_gamma(
            eta_q_gamma=q.eta_q_gamma,
            ev_q_gamma=q.gamma,
            ev_q_gamma_outer=q.gamma_outer,
            negative_kl_q_p_gamma=q.negative_kl_q_p_gamma,
            ev_q_eps_alpha=q.eps_alpha,
            ev_q_tau_alpha=q.tau_alpha,
            ev_q_delta_gamma=q.delta_gamma,
            ev_q_delta_gamma_sq=q.delta_gamma_sq,
            h_per_basket=data.h_per_basket,
            h_outer_sum_first=data.h_outer_sum_first,
            h_outer_sum_not_first=data.h_outer_sum_not_first,
            prior=prior,
            ib_first=data.ib_first,
            ib_not_first=data.ib_not_first,
        )

    if not is_fixed.rho:
        model.functions.update_q_rho(
            eta_q_rho=q.eta_q_rho,
            ev_q_rho=q.rho,
            ev_q_rho_outer=q.rho_outer,
            negative_kl_q_p_rho=q.negative_kl_q_p_rho,
            ev_q_eps_alpha=q.eps_alpha,
            ev_q_tau_alpha=q.tau_alpha,
            mu_q_alpha=q.mu_q_alpha,
            sigma_sq_q_alpha=q.sigma_sq_q_alpha,
            prior=prior,
            ib_not_first=data.ib_not_first,
            ib_not_last=data.ib_not_last,
        )

    if not is_fixed.delta:
        model.functions.update_q_delta(
            eta_q_delta=q.eta_q_delta,
            ev_q_delta=q.delta,
            ev_q_delta_sq=q.delta_sq,
            ev_q_negative_kl_q_p_delta=q.negative_kl_q_p_delta,
            ev_q_eps_alpha=q.eps_alpha,
            ev_q_tau_alpha=q.tau_alpha,
            prior=prior,
            dim_i=data.dim_i,
            ib_first=data.ib_first,
        )

    if not is_fixed.delta_kappa:
        model.functions.update_q_delta_kappa(
            eta_q_delta_kappa=q.eta_q_delta_kappa,
            ev_q_delta_kappa=q.delta_kappa,
            ev_q_delta_kappa_sq=q.delta_kappa_sq,
            ev_q_negative_kl_q_p_delta_kappa=q.negative_kl_q_p_delta_kappa,
            ev_q_eps_alpha=q.eps_alpha,
            ev_q_kappa=q.kappa,
            ev_q_kappa_sq=q.kappa_sq,
            ev_q_tau_alpha=q.tau_alpha,
            prior=prior,
            ib_first=data.ib_first,
        )

    if not is_fixed.delta_beta:
        model.functions.update_q_delta_beta(
            eta_q_delta_beta=q.eta_q_delta_beta,
            ev_q_delta_beta=q.delta_beta,
            ev_q_delta_beta_sq=q.delta_beta_sq,
            ev_q_negative_kl_q_p_delta_beta=q.negative_kl_q_p_delta_beta,
            ev_q_eps_alpha=q.eps_alpha,
            ev_q_beta=q.beta,
            ev_q_beta_outer=q.beta_outer,
            ev_q_tau_alpha=q.tau_alpha,
            dim_m=M,
            prior=prior,
            x=data.x,
            x_outer_sum_first=data.x_outer_sum_first,
            ib_first=data.ib_first,
        )

    if not is_fixed.delta_gamma:
        model.functions.update_q_delta_gamma(
            eta_q_delta_gamma=q.eta_q_delta_gamma,
            ev_q_delta_gamma=q.delta_gamma,
            ev_q_delta_gamma_sq=q.delta_gamma_sq,
            ev_q_negative_kl_q_p_delta_gamma=q.negative_kl_q_p_delta_gamma,
            ev_q_eps_alpha=q.eps_alpha,
            ev_q_gamma=q.gamma,
            ev_q_gamma_outer=q.gamma_outer,
            ev_q_tau_alpha=q.tau_alpha,
            dim_m=M,
            prior=prior,
            h=data.h,
            h_outer_sum_first=data.h_outer_sum_first,
            ib_first=data.ib_first,
        )

    # Recompute ev_q_eps_alpha and compute ev_q_sum_ib_eps_alpha_sq
    model.functions.calc_ev_q_eps_alpha(
        ev_q_eps_alpha=q.eps_alpha,
        mu_q_alpha=q.mu_q_alpha,
        ev_q_kappa=q.kappa,
        ev_q_beta=q.beta,
        ev_q_gamma=q.gamma,
        ev_q_rho=q.rho,
        ev_q_delta=q.delta,
        ev_q_delta_kappa=q.delta_kappa,
        ev_q_delta_beta=q.delta_beta,
        ev_q_delta_gamma=q.delta_gamma,
        data=data,
    )

    model.functions.calc_ev_q_sum_ib_eps_alpha_sq(
        ev_q_sum_ib_eps_alpha_sq=q.sum_ib_eps_alpha_sq,
        mu_q_alpha=q.mu_q_alpha,
        sigma_sq_q_alpha=q.sigma_sq_q_alpha,
        ev_q_alpha_sq=q.alpha_sq,
        ev_q_kappa=q.kappa,
        ev_q_kappa_sq=q.kappa_sq,
        ev_q_beta=q.beta,
        ev_q_beta_outer=q.beta_outer,
        ev_q_gamma=q.gamma,
        ev_q_gamma_outer=q.gamma_outer,
        ev_q_rho=q.rho,
        ev_q_rho_outer=q.rho_outer,
        ev_q_delta=q.delta,
        ev_q_delta_sq=q.delta_sq,
        ev_q_delta_kappa=q.delta_kappa,
        ev_q_delta_kappa_sq=q.delta_kappa_sq,
        ev_q_delta_beta=q.delta_beta,
        ev_q_delta_beta_sq=q.delta_beta_sq,
        ev_q_delta_gamma=q.delta_gamma,
        ev_q_delta_gamma_sq=q.delta_gamma_sq,
        dim_m=M,
        data=data,
    )

    if not is_fixed.tau_alpha:
        model.functions.update_q_tau_alpha(
            eta_q_tau_alpha=q.eta_q_tau_alpha,
            ev_q_tau_alpha=q.tau_alpha,
            ev_q_log_tau_alpha=q.log_tau_alpha,
            ev_q_negative_kl_q_p_tau_alpha=q.negative_kl_q_p_tau_alpha,
            ev_q_sum_ib_eps_alpha_sq=q.sum_ib_eps_alpha_sq,
            prior=prior,
            total_baskets=data.total_baskets,
            dim_m=M,
        )

    if not is_fixed.mu_kappa:
        model.functions.update_q_mu_kappa(
            eta_q_mu_kappa=q.eta_q_mu_kappa,
            ev_q_mu_kappa=q.mu_kappa,
            ev_q_mu_kappa_outer=q.mu_kappa_outer,
            ev_q_negative_kl_q_p_mu_kappa=q.negative_kl_q_p_mu_kappa,
            sum_ev_q_kappa=np.sum(q.kappa, axis=0),
            ev_q_lambda_kappa=q.lambda_kappa,
            prior=prior,
            dim_i=data.dim_i,
        )

    if not is_fixed.lambda_kappa:
        model.functions.update_q_lambda_kappa(
            eta_q_lambda_kappa=q.eta_q_lambda_kappa,
            ev_q_lambda_kappa=q.lambda_kappa,
            ev_q_log_det_lambda_kappa=q.log_det_lambda_kappa,
            ev_q_negative_kl_q_p_lambda_kappa=q.negative_kl_q_p_lambda_kappa,
            sum_ev_q_kappa=np.sum(q.kappa, axis=0),
            sum_ev_q_kappa_outer=np.sum(q.kappa_outer, axis=0),
            ev_q_mu_kappa=q.mu_kappa,
            ev_q_mu_kappa_outer=q.mu_kappa_outer,
            prior=prior,
            dim_i=data.dim_i,
        )

    return q



# 1. The routine function takes several input parameters, including the variational parameters (`q`), data, prior information, fixed parameters, and optimization settings.
# 3. The function calculates the initial Evidence Lower Bound (ELBO) using the `model.elbo.compute_elbo_container` function and stores it in the `elbo_start_routine` variable.
# 5. A CSV file named "elbo.csv" is created to store the ELBO values.
# 6. A dictionary named `tallies` is initialized to keep track of updates to specific parameters during the optimization process.
# 7. If profiling is enabled (based on `misc_settings.profile_code`), a profiling object is created to measure the performance of the code.
# 8. The optimization loop begins, iterating `n_iter` times.
# 9. The code checks if the current iteration needs to be saved or if it is the last iteration.
# 10. The tallies for updates to `q(alpha)` parameters are reset.
# 11. If enabled (`misc_settings.check_state_consistency`), the code checks the consistency of the variational state.
# 12. A single iteration of the optimization routine is performed by calling the `iteration` function with appropriate parameters.
# 13. If enabled (`misc_settings.check_state_consistency`), the code checks the consistency of the variational state again.
# 14. The ELBO value after the iteration is computed using `model.elbo.compute_elbo_container`.
# 15. If it is a printing iteration (based on `misc_settings.n_print_per`), information about the current iteration, such as the ELBO value, the difference from the previous iteration, and the acceptance rates of proposals for `q(alpha)`, is printed to the console.
# 16. The ELBO value after the iteration is written to the CSV file.
# 17. The current ELBO value is updated.
# 18. The ELBO value after the iteration is stored in the `elbo_dict` dictionary.
# 19. If the current iteration needs to be saved or it is the last iteration, the variational state is saved in a compressed numpy file.
# 20. If profiling is enabled, the profiling object is disabled and the profiling statistics are saved to a file.
# 21. The total number of iterations and the time spent on optimization are printed to the console.
# 22. The function returns the final variational parameters (`q`) and the dictionary of ELBO values (`elbo_dict`).
# The code updates the local variational parameters q using the model.functions.update_q_local function. These parameters include z, alpha, kappa, and other related variables. The updated values are stored in the q object.

# The code then updates the global variational parameter phi using the model.functions.update_q_phi function. If the phi parameter is not fixed, its value is updated based on the current q values and other information such as eta_q_phi, negative_kl_q_p_phi, and counts_phi.

# Similarly, the code updates the global variational parameters beta, gamma, rho, delta, delta_kappa, and delta_beta if they are not fixed. Each update is performed using a dedicated function, such as model.functions.update_q_beta for beta, model.functions.update_q_gamma for gamma, and so on. These updates involve various computations based on the current q values and other relevant information.

# The code recalculates ev_q_eps_alpha and ev_q_sum_ib_eps_alpha_sq using the model.functions.calc_ev_q_eps_alpha and model.functions.calc_ev_q_sum_ib_eps_alpha_sq functions, respectively. These calculations involve updating the values based on the updated q parameters and other related information.

# Finally, the code updates the variational parameter tau_alpha using the model.functions.update_q_tau_alpha function if it is not fixed. The update is based on the current q values, ev_q_sum_ib_eps_alpha_sq, and other relevant information.

# The code also updates the variational parameters mu_kappa and lambda_kappa if they are not fixed. These updates are performed using the model.functions.update_q_mu_kappa and model.functions.update_q_lambda_kappa functions, respectively. The updates involve calculations based on the current q values, sum_ev_q_kappa, sum_ev_q_kappa_outer, and other relevant information.

# Finally, the updated q object is returned.