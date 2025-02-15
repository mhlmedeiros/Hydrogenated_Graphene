
"""
    Script to define a honeycomb lattice (Graphene) with periodic boundary
    conditions using Python-kwant. To keep things simple, we're going to
    consider hoppings between nearest-neighbors and disregard the spin degree
    of freedom.

    author: Marcos De Medeiros
    date: 09/08/2021
"""


import kwant
import tinyarray
import numpy as np
import matplotlib.pyplot as plt

import scipy.linalg as la
import scipy.sparse.linalg as sla


## DEFINITIONS:
graphene = kwant.lattice.honeycomb(name='G', norbs=2)
A, B = graphene.sublattices

hydrogen = kwant.lattice.honeycomb(name='H', norbs=2)
HA, HB = hydrogen.sublattices

zeros_2x2 = tinyarray.array([[0,0],[0,0]])
sigma_0 = tinyarray.array([[1,0],[0,1]])
sigma_x = tinyarray.array([[0,1],[1,0]])
sigma_y = tinyarray.array([[0,-1j],[1j,0]])
sigma_z = tinyarray.array([[1,0],[0,-1]])


class Permition_PBC:
    def __init__(self, max_a1_component, max_a2_component, delta=1):
        self.a1_inf = delta
        self.a1_sup = max_a1_component - delta
        self.a2_inf = delta
        self.a2_sup = max_a2_component - delta

    def is_allowed(self, site):
        a1, a2 = site.tag
        return self.a1_inf <= a1 < self.a1_sup and self.a2_inf <= a2 < self.a2_sup

class FormatMapSites:

    def __init__(self, allowed_sites, adatom_sites):
        self.allowed = allowed_sites
        self.adatoms = adatom_sites

    def color(self, site):
        if site in self.allowed:
            color = 'C1'
        elif site in self.adatoms and site.family == A:
            color = 'r'
        elif site in self.adatoms and site.family == B:
            color = 'magenta'
#         elif site.family == A:
#             color = 'w'
        else:
            color = 'w'
        return color

    def line_width(self, site):
        if site in self.allowed or site in self.adatoms:
            lw = 0
        else:
            lw = 0.05
        return lw


def make_system(N1=10, N2=20, pot=0, t=2.6):
    #### Define the scattering region. ####
    syst = kwant.Builder()
    for a1 in range(N1):
        for a2 in range(N2):
            syst[A(a1, a2)] = -pot * sigma_0
            syst[B(a1, a2)] = -pot * sigma_0

    # specify the hoppings of the graphene lattice in the
    # format expected by builder.HoppingKind
    hoppings = (((0, 0), A, B), ((0, 1), A, B), ((-1, 1), A, B))
    syst[[kwant.builder.HoppingKind(*hopping) for hopping in hoppings]] = -t * sigma_0

    ## Horizontal hoppings PBC
    for j in range(1, N2):
        syst[A(N1-1, j), B(0,j-1)] = -t * sigma_0

    ## Vertical hopping PBC
    for i in range(N1):
        syst[B(i, N2-1), A(i, 0)] = -t * sigma_0
        syst[B((i+1) % N1, N2-1), A(i, 0)] = -t * sigma_0

    return syst

def insert_adatoms_randomly_pbc(system, n_cells_a1, n_cells_a2, adatom_concentration, params):

    ## INSERTING ADATOMS:
    test_pbc = Permition_PBC(n_cells_a1, n_cells_a2, delta=2)
    print("Collecting the allowed sites to place adatoms...", end=' ')
    allowed_sites_pbc = [site for site in system.sites() if test_pbc.is_allowed(site)]
    print("OK")

    print("Inserting adatoms randomly...", end=' ')
    n_Carbon_sites = n_cells_a1 * n_cells_a2 * 2
    n_Hydrogen_sites = int(n_Carbon_sites // (100/adatom_concentration))
    number_of_adatoms_pbc = max(2, n_Hydrogen_sites)
    list_of_A_adatom_sites_pbc, list_of_B_adatom_sites_pbc, allowed_sites_pbc_2 = get_adatom_positions_balanced(
                                                                        number_of_adatoms_pbc,
                                                                        allowed_sites_pbc)
    A_adatoms_tags_pbc = [site.tag for site in list_of_A_adatom_sites_pbc]
    B_adatoms_tags_pbc = [site.tag for site in list_of_B_adatom_sites_pbc]
    CH_sites_pbc = list_of_A_adatom_sites_pbc + list_of_B_adatom_sites_pbc

    all_neighbors_pbc = [get_neighbors(system, CH) for CH in CH_sites_pbc]
    all_NN_neighbors_pbc = [a[0] for a in all_neighbors_pbc]
    all_NNN_neighbors_pbc = [a[1] for a in all_neighbors_pbc]

    T = params['T']          #  5.5 eV Fluorine,  7.5 eV Hydrogen: ADATOM-CARBON HOPPING
    epsilon = params['eps']  # -2.2 eV Fluorine, 0.16 eV Hydrogen: ON-SITE ENERGY FOR ADATOM

    for tagA in A_adatoms_tags_pbc:
        system[HA(*tagA)] = sigma_0 * epsilon     # on-site
        system[A(*tagA), HA(*tagA)] = sigma_0 * T # hopping with C_H

    for tagB in B_adatoms_tags_pbc:
        system[HB(*tagB)] = sigma_0 * epsilon     # on-site
        system[B(*tagB), HB(*tagB)] = sigma_0 * T # hopping with C_H

    print("OK")

    print("Considering the SOC terms...", end=" ")
    ## Calculate and include the Adatom induced spin-orbit coupling (ASO)
    include_all_ASO(system, CH_sites_pbc, all_NNN_neighbors_pbc, Lambda_I=params['Lambda_I'])

    ## Calculate and include into the system the Bychkov-Rashba spin-orbit coupling (BR)
    include_all_BR(system, CH_sites_pbc, all_NN_neighbors_pbc, Lambda_BR=params['Lambda_BR'])

    ## Calculate and include into the system the Pseudo-spin inversion asymmetry spin-orbit coupling (PIA)
    include_all_PIA(system, all_NN_neighbors_pbc, Lambda_PIA=params['Lambda_PIA'], iso=False)
    print("OK")

    print("Formating sites for plotting...", end=' ')
    format_sites_3 = FormatMapSites(allowed_sites_pbc_2, CH_sites_pbc)
    print("OK")
    return system

def insert_adatoms(system, adatom_concentration, n_cells_a1, n_cells_a2, verbatim=True):
    n_Carbon_sites = n_cells_a1 * n_cells_a2 * 2
    n_Hydrogen_sites = int(n_Carbon_sites // (100/adatom_concentration))

    if verbatim:
        print("Number of Carbon atoms = {:d}".format(n_Carbon_sites))
        print("Number of adatoms = {:d}".format(n_Hydrogen_sites))
        print("Adatoms' concentration = {:f} %".format(adatom_concentration))


    possible_tags_a1 = np.arange(n_cells_a1)
    possible_tags_a2 = np.arange(n_cells_a2)
    random_tags_a1 = np.random.choice(possible_tags_a1, n_Hydrogen_sites, replace=False)
    random_tags_a2 = np.random.choice(possible_tags_a2, n_Hydrogen_sites, replace=False)

    system = make_system(N1=n_cells_a1, N2=n_cells_a2)
    for i, j in zip(random_tags_a1, random_tags_a2):
        pos_adatom = (i, j)
        system = insert_single_adatom(system, pos_adatom)

    return system

def insert_single_adatom(system, pos_adatom, t=7.5, V=0.16):
    n1, n2 = pos_adatom
    system[HA(n1,n2)] = V
    system[HA(n1,n2), A(n1,n2)] = t
    return system


## INSERTING RANDOMLY LOCATED ADATOMS
def get_adatom_positions_balanced(total_number_of_adatoms, allowed_sites):
    A_adatoms_to_place = total_number_of_adatoms // 2
    B_adatoms_to_place = total_number_of_adatoms - A_adatoms_to_place

    list_of_A_adatoms = []
    list_of_B_adatoms = []

    while A_adatoms_to_place or B_adatoms_to_place:
#         print("A-adatoms do place = {:d}".format(A_adatoms_to_place))
#         print("B-adatoms do place = {:d}".format(B_adatoms_to_place))

        site_adatom = allowed_sites[np.random.choice(len(allowed_sites))]

        if site_adatom.family == A and A_adatoms_to_place:
            list_of_A_adatoms.append(site_adatom)
            allowed_sites = exclude_neighboring_sites(site_adatom, allowed_sites)
            A_adatoms_to_place -= 1
        elif site_adatom.family == B and B_adatoms_to_place:
            list_of_B_adatoms.append(site_adatom)
            allowed_sites = exclude_neighboring_sites(site_adatom, allowed_sites)
            B_adatoms_to_place -= 1

#         print("Number of allowed sites: ",len(allowed_sites))

        if not allowed_sites:
            break

    return list_of_A_adatoms, list_of_B_adatoms, allowed_sites

def get_adatom_positions_by_family(number_of_adatoms, allowed_sites, family=None):
    list_of_adatom_sites = []
    i = 1
    print('Number of adatoms wanted = ', number_of_adatoms)
    if family != None:
        allowed_sites = [site for site in allowed_sites if site.family == family]
    while i <= number_of_adatoms:
        site_adatom = allowed_sites[np.random.choice(len(allowed_sites))]
        allowed_sites = exclude_neighboring_sites(site_adatom, allowed_sites)
        list_of_adatom_sites.append(site_adatom)
#         print(i)
#         print('number of allowed sites = ', len(allowed_sites))
        if len(allowed_sites) < 1:
            print("Only {:d} adatoms were possible!".format(i))
            break
        i += 1
    print("{:d} adatoms were inserted".format(i-1))
    return list_of_adatom_sites, allowed_sites

def exclude_neighboring_sites(adatom_site, list_of_sites, radius=2):
    sites_to_exclude = neighboring_sites(adatom_site, list_of_sites, radius)
    for site in sites_to_exclude:
        list_of_sites.remove(site)
    return list_of_sites

def neighboring_sites(adatom_site, list_of_sites, radius):
    list_of_neighboring_sites = []
    xA, yA = adatom_site.pos
    for site in list_of_sites:
        x, y = site.pos
        if (x-xA)**2 + (y-yA)**2 <= radius**2:
            list_of_neighboring_sites.append(site)
    return list_of_neighboring_sites


## SPIN-ORBIT COUPLING DUE TO THE ADATOMS:
def get_neighbors(system, C_H_site):
    """
    Returns a list containing 2 other lists:
        - nn_list = list of nearest neighbors sites
        - nnn_list = list of next nearest neighbors sites
    """
    site_tag = C_H_site.tag
    site_sub = C_H_site.family
    nn_list = get_nn(system, site_tag, site_sub)
    nnn_list = get_nnn(system, site_tag, site_sub)
    return [nn_list, nnn_list]

def get_nn(system, tag, sub_s):
    """
    system := kwant.builder.Builder
    tag    := tuple (i,j) of the site's tag
    sub_s  := site's sublattice

    Notice that
    """
    list_sub_lat = [A, B]
    list_sub_lat.remove(sub_s) # remove the sublattice to which the site belongs
    sub_nn, = list_sub_lat     # extract the sublattice of the neighbors
    # print(sub_nn.name[-1])
    name_indx = int(sub_s.name[-1])
    delta = +1 if name_indx == 0 else -1
#     print(delta)
    i,j = tag
    nn_tag_list = [(i,j), (i+delta,j-delta), (i,j-delta)]
    nn_sites = [
        sub_nn(*t) for t in nn_tag_list if sub_nn(*t) in system
    ]
#     for site in nn_sites:
#         print(site)
    return nn_sites

def get_nnn(system, tag, sub_s):
    """
    system := kwant.builder.Builder
    tag    := tuple (i,j) of the site's tag
    sub_s  := site's sublattice

    Notice that
    """
    #sub_nnn = sub_s

    i,j = tag
    nnn_tag_list = [(  i,j+1), (i+1,  j),
                    (i+1,j-1), (  i,j-1),
                    (i-1,  j), (i-1,j+1)]
    nnn_sites = [
        sub_s(*t) for t in nnn_tag_list if sub_s(*t) in system
    ]
#     for site in nnn_sites:
#         print(site)
    return nnn_sites

# FOR EACH ADATOM:
def include_ASO_sitewise(system, CH_site, NNN_site, Lambda_I):
    """
    Define and replace the hopping between CH_site and one of its NNN sites,
    which is identified here as NNN_site.
    """
    # 1.1. Identify the hopping 1/2
    delta_tag = list(NNN_site.tag - CH_site.tag)
    if delta_tag in ([0,1], [1,-1], [-1,0]): sign = -1
    else: sign = +1

    # 1.2. Identify the hopping 2/2
    family_id  = 1 - 2 * int(CH_site.family.name[-1]) ## 1 (-1) if sublattice == A (B)

    # 3. Define the hopping
    H_asoc = sign * family_id * 1j/3 * Lambda_I/np.sqrt(3) * sigma_z # clockwise
    system[CH_site, NNN_site] = H_asoc ## sytem[sublat_1(target), sublat_2(source)]

def include_BR_sitewise(system, CH_site, NN_site, Lambda_BR):
    """
    Update the hopping between the CH_site and the NN_site to include
    the Bychkov-Rashba SOC.
    """
    # 1. Identify the hopping:
    dx, dy = np.sqrt(3) * (CH_site.pos - NN_site.pos)
    H_BR = (2j/3) * Lambda_BR * (dy * sigma_x - dx * sigma_y) ## (S X d_ij)_z

    # 2. Define the hopping
    system[CH_site, NN_site] += H_BR

def include_PIA_sitewise(system, site_target, site_source, Lambda_PIA, iso):
    """
    Define the PIA hopping and add to the already existent hopping between
    site_target and site_source.
    """
    # 2. Identify the hopping:
    Dx, Dy = site_target.pos - site_source.pos

    # 3. Define the hopping
    H_PIA =  2j/3 * Lambda_PIA * (Dy * sigma_x - Dx * sigma_y) ## (S x D_ij)_z
    if iso:
        system[site_target, site_source] += H_PIA
    else:
        system[site_target, site_source] = H_PIA


# FOR ALL ADATOMS:
def include_all_ASO(system, all_CH_sites, all_NNN_neighbors, Lambda_I=1):
    for CH_site, NNN_sites in zip(all_CH_sites, all_NNN_neighbors):
        for NNN_site in NNN_sites:
            include_ASO_sitewise(system, CH_site, NNN_site, Lambda_I)

def include_all_BR(system, all_CH_sites, all_NN_neighbors, Lambda_BR=1):
    for CH_site, NN_sites in zip(all_CH_sites, all_NN_neighbors):
        for NN_site in NN_sites:
            include_BR_sitewise(system, CH_site, NN_site, Lambda_BR)

def include_all_PIA(system, all_NN_neighbors, Lambda_PIA=1, iso=True):
    for NN_sites in all_NN_neighbors:
        targets = [NN_sites[(i+1)%3] for i in range(3)]
        for site1, site2 in zip(targets, NN_sites):
            include_PIA_sitewise(system, site1, site2, Lambda_PIA, iso)


## CALCULATE DENSITY OF STATES:
def dos_kpm(system, energies, additional_vectors=50, resolution=None):
    fsystem = system.finalized()
    spectrum = kwant.kpm.SpectralDensity(fsystem)
    spectrum.add_vectors(additional_vectors)
    if resolution: spectrum.add_moments(energy_resolution=resolution)
    density_kpm = spectrum(energies)
    return density_kpm

def delta_approx(E, Em, eps):
    return (eps/np.pi)/((E-Em)**2 + eps**2)

def dos_manual(E_array, Eigenvalues, eps=0.1):
    dos = np.zeros_like(E_array)
    for Em in Eigenvalues:
        dos += delta_approx(E_array, Em, eps)
    return dos

def plot_density_of_states(E, DOS_pristine, DOS_adatoms):
    # fig, ax = plt.subplots(ncols=2, figsize=(8,8))
    # ax[0].tick_params(labelsize=20)
    # ax[0].plot(E, np.real(DOS_pristine), label='Pristine', color='k', linestyle='--')
    # ax[0].plot(E, np.real(DOS_adatoms), label='Adatoms', color='C2', linestyle='-')
    # ax[0].legend(fontsize=20)
    # ax[0].set_xlabel(r'$E$ [eV]',fontsize=24)
    # ax[0].set_ylabel('DOS [a.u.]',fontsize=24)
    #
    # ax[1].tick_params(labelsize=20)
    # ax[1].plot(E, np.real(DOS_adatoms)-np.real(DOS_pristine), label='Difference', color='C2', linestyle='-')
    # ax[1].legend(fontsize=20)
    # ax[1].set_xlabel(r'$E$ [eV]',fontsize=24)
    # ax[1].set_yticks([])
    # plt.tight_layout(pad=0.1)
    fig, ax = plt.subplots(figsize=(5,5))
    ax.tick_params(labelsize=20)
    ax.plot(E, np.real(DOS_pristine), label='Pristine', color='k', linestyle='--')
    ax.plot(E, np.real(DOS_adatoms), label='Adatoms', color='C2', linestyle='-')
    ax.legend(fontsize=20)
    ax.set_xlabel(r'$E$ [eV]',fontsize=24)
    ax.set_ylabel('DOS [a.u.]',fontsize=24)
    ax.axes.yaxis.set_ticklabels([])
    plt.tight_layout()
    plt.show()


## PLOTTING HELPERS
def hopping_colors(site1, site2):
    if site1.family == site2.family:
        color='red'
    else:
        color='black'
    return color

def hopping_lw(site1, site2):
    return 0.07 if site1.family == site2.family else 0.05

def family_colors_H(site):
        if site.family == A:
            color = 'k'
        elif site.family == B:
            color = 'k'
        elif site.family == HA:
            color = 'blue'
        elif site.family == HB:
            color = 'blue'
        else:
            color = 'cyan'
        return color

def site_size_function(site):
    if site.family == HA or site.family == HB:
        size = 0.4
    else:
        size = 0.1
    return size

def plor_system_format(system):
    print("Plotting...", end=' ')
    ## Figure
    fig, ax = plt.subplots(figsize=(20,5))
    # kwant.plot(system,
    #            site_color=format_sites_3.color,
    #            hop_color=hopping_colors,
    #            hop_lw=hopping_lw,
    #            site_lw=format_sites_3.line_width,
    #            ax=ax)
    kwant.plot(system,
               site_size = site_size_function,
               site_color=family_colors_H,
               hop_color=hopping_colors,
               hop_lw=hopping_lw,
               site_lw=format_sites_3.line_width,
               ax=ax)
    ax.set_aspect('equal')
    ax.axis('off')
    ax.set_title('Possible location for Adatoms in orange', fontsize=20)
    plt.show()
    print("OK")


def main():
    n_cells_a1 = 30
    n_cells_a2 = 30
    adatom_concentration = 0.125  # [% of Carbon atoms]

    ## BUILDING PRISTINE SYSTEM:
    system = make_system(N1=n_cells_a1, N2=n_cells_a2, pot=0, t=2.6)

    ## CALCULATING THE DENSITY OF STATES:
    energies = np.linspace(-0.5, 0.5, 501)
    density_pristine = dos_kpm(system, energies, resolution=0.03)
    # np.savez('../results/dos/density_of_states_pristine_pbc_300x300_resolution_0,03.npz', energies=energies, density=density_pristine)

    ## INSERTING ADATOMS:
    adatom_H_params = dict(T = 7.5, eps = 0.16, Lambda_I = -0.21e-3, Lambda_BR = 0.33e-3, Lambda_PIA = -0.77e-3)
    adatom_F_params = dict(T = 5.5, eps = -2.2, Lambda_I = 3.3e-3, Lambda_BR = 11.2e-3, Lambda_PIA = -7.3e-3)
    system = insert_adatoms_randomly_pbc(system, n_cells_a1, n_cells_a2, adatom_concentration, params=adatom_F_params)
    # system = insert_adatoms(system, adatom_concentration, n_cells_a1, n_cells_a2)

    density_adatoms = dos_kpm(system, energies, resolution=0.03)
    # np.savez('../results/dos/density_of_states_with_0,125_F_adatoms_pbc_300x300_resolution_0,03.npz', energies=energies, density=density_adatoms)

    plot_density_of_states(energies, density_pristine, density_adatoms)



if __name__ == '__main__':
    main()
