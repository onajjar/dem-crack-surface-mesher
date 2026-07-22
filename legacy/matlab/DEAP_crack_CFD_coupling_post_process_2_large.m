%% DEAP_crack_2_STL
% Transforms a DEAP crack into an STL mesh
%
% The extracted macrocrack corresponds to the largest connected component 
% from the graph composed of the vertices and edges of the microcracks. 
% It is then opened along an axis set by the user from the displacement field. 
% A surface is finally fitted on each face of the crack.
% Four surfaces are added between the two faces. 
% The created meshes are output in STL format to be opened with a CAD software.
% 
% Auteurs :
%
% * Cécile Oliver-Leblond - <cecile.oliver@ens-paris-saclay.fr>

% Modified: 
% Omar NAJJAR - <omar.najjar@ens-paris-saclay.fr>

% Versions :
%
% * 18/08/2022 : Initial code
% * 29/06/2023 : Modified code

clear
close all
clc
% LASTN = maxNumCompThreads('automatic');

% Drwaing paramertes 
font_weight = 30 ; 

line_width = 3 ; 
% Set default properties
set(groot, 'defaultAxesFontSize', font_weight);
set(groot, 'defaultAxesFontWeight', 'bold');
set(groot, 'defaultTextFontWeight', 'bold');
set(groot, 'defaultLegendFontWeight', 'bold');
set(groot, 'defaultColorbarFontWeight', 'bold');
set(groot, 'defaultTextInterpreter', 'latex');
set(groot, 'defaultLegendInterpreter', 'latex');
set(groot, 'defaultAxesTickLabelInterpreter', 'latex');
% Input parameters

% Repository and Files
rep_post = 'C:\Users\onajjar\Desktop\castem_trial\original_input\2_large'; 

%%
% spa_num_values = [5, 100, 500,1000,1500] ; 
ti = 100 ; 
cr_pa = 1 ; 
spa_smo_values = [0.1] ; 
spa_num = 20 ;
opmin = 10e-6 ; 
crack_glob_or = 'ZX' ; 
bounding_box = [0.0 0.05 0.0 0.05 0.0 0.05];
f_mag = 1 ; 
% Please, set f_mag to 1 for the real macro-crack since it is just for
% visulisation
for i=1:length(spa_smo_values)
    spa_smo = spa_smo_values(i) ; 
    [xrange, yrange, zfit_zmax, zfit_zmin] = DEAP_crack_CFD_coupling(rep_post, ...
        'time_step', ti, ...
        'cr_pa', cr_pa, ...
        'spa_smo', spa_smo, ...
        'spa_num', spa_num, ...
        'opmin', opmin, ...
        'crack_glob_or', crack_glob_or, ...
        'f_mag', f_mag, ...
        'bounding_box', bounding_box, ...
        'vtk_output', false, ...
        'stl_outputs', false, ...
        'ext_csv', true, ...
        'tortousity_analysis', false,...
        'connected_components_graph', false, ...
        'full_graph', false, ...
        'simplified_graph',false, ...
        'crack_open_plot', false, ...
        'crack_surface_graph', true);
end 

