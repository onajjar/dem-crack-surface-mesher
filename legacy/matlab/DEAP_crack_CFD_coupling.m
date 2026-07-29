function [xrange_i,yrange_i,zfit_zmax_i,zfit_zmin_i, crack_comp, zD_zmin, zD_zmax] = DEAP_crack_CFD_coupling(rep_post, varargin)
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
% * Omar Najjar           - <omar.najjar@ens-paris-saclay.fr>

% Versions :
%
% * 18/08/2022 : Initial code
% * 22/01/2026 : Last version code
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

params = inputParser;
params.FunctionName = 'DEAP_crack_CFD_coupling';

params.addRequired('rep_post', @ischar); % Required argument: rep_post (string)

% Non-logical variables
params.addParameter('time_step', [], @(x) isempty(x) || (isnumeric(x) && isscalar(x) && x > 0));
% params.addParameter('cr_pa', 1, @isnumeric);
params.addParameter('cr_pa', [], @(x) isempty(x) || isnumeric(x));

params.addParameter('spa_smo', 0.05, @isnumeric);
params.addParameter('spa_num', 50, @isnumeric);
params.addParameter('opmin', 1.0e-8, @isnumeric);
params.addParameter('crack_glob_or', 'ZX', @ischar);
params.addParameter('f_mag', 1, @isnumeric);
params.addParameter('bounding_box', [], @(x) isnumeric(x) && numel(x) == 6);



% Logical variables
params.addParameter('full_graph', false, @islogical);
params.addParameter('simplified_graph', false, @islogical);
params.addParameter('connected_components_graph', false, @islogical);
params.addParameter('crack_surface_graph', false, @islogical);
params.addParameter('crack_open_plot', false, @islogical);
params.addParameter('vtk_output', false, @islogical);
params.addParameter('stl_outputs', false, @islogical);
params.addParameter('ext_csv', false, @islogical);
params.addParameter('run_mesher', false, @islogical);
params.addParameter('estimate_fracture_area', false, @islogical);
params.addParameter('tortousity_analysis', false, @islogical);



% Parse the inputs
params.parse(rep_post, varargin{:});
inputs = params.Results;

cr_pa = inputs.cr_pa;
spa_smo = inputs.spa_smo;
spa_num = inputs.spa_num;
opmin = inputs.opmin;
crack_glob_or = inputs.crack_glob_or;
f_mag = inputs.f_mag;



full_graph = inputs.full_graph;
simplified_graph = inputs.simplified_graph;
connected_components_graph = inputs.connected_components_graph;
crack_surface_graph = inputs.crack_surface_graph;
crack_open_plot = inputs.crack_open_plot;
vtk_output = inputs.vtk_output;
stl_outputs = inputs.stl_outputs;
ext_csv = inputs.ext_csv;
% run_mesher = inputs.run_mesher;
estimate_fracture_area = inputs.estimate_fracture_area;
tortousity_analysis = inputs.tortousity_analysis;

% fprintf('Processing directory: %s\n', rep_post);
% fprintf('Parameters:\n');
% fprintf('  ti (time): %.2f\n', time_step);
% fprintf('  cr_pa: %d\n', cr_pa);
% fprintf('  spa_smo: %.2f\n', spa_smo);
% fprintf('  spa_num: %d\n', spa_num);
% fprintf('  opmin: %.2e\n', opmin);
% fprintf('  crack_glob_or: %s\n', crack_glob_or);
% fprintf('  full_graph: %d\n', full_graph);
% fprintf('  simplified_graph: %d\n', simplified_graph);
% fprintf('  connected_components_graph: %d\n', connected_components_graph);
% fprintf('  crack_surface_graph: %d\n', crack_surface_graph);
% fprintf('  vtk_output: %d\n', vtk_output);
% fprintf('  stl_outputs: %d\n', stl_outputs);
% fprintf('  ext_csv: %d\n', ext_csv);
% fprintf('  run_mesher: %d\n', run_mesher);
% fprintf('  estimate_fracture_area: %d\n', estimate_fracture_area);
% fprintf('  tortousity_analysis: %d\n', tortousity_analysis);





% Main code starts here
file_hdf5 = fullfile(rep_post,'deap_post.h5');
file_hdf5_out = fullfile(rep_post, 'deap_output.h5') ;
% file_hdf5_mesh = fullfile(rep_post, 'deap_mesh.h5') ;
%
% Get the total number of time steps
% The rest of the Matlab file is written taking into account that the crack
% is globally aligned along the XY plane and opens in the Z direction.
% The columd if this is not the case.
% f_mesh = h5info(file_hdf5_mesh);
f_out = h5info(file_hdf5_out); % Read the HDF5 file information
% f_post = h5info(file_hdf5); 

% mesh_keys = {f_mesh.Datasets.Name}; 
out_keys = {f_out.Datasets.Name}; % Get the names of the datasets in the HDF5 file
% post_keys = {f_post.Datasets.Name};


n_time_steps = sum(startsWith(out_keys, 'disp_trans_'));  % computed

% ti_list = 1:n_time_steps; 

if isempty(inputs.time_step)
    ti_list = 1:n_time_steps;              % loop over all time steps
else
    ti = min(inputs.time_step, n_time_steps);  % clip to max
    ti_list = ti;                           % loop only once
end

% Geometry Limits
% In the global coordinates i.e. those of DEAP
% Get the geometry limit



file_geom = fullfile(rep_post, 'input.boundary');
fileID = fopen(file_geom, 'r');

% Check if the file was successfully opened
if fileID == -1
    disp('input.boundary file cannot be found. Input bounding box values will be used.');
    
    if isfield(inputs, 'bounding_box') && isnumeric(inputs.bounding_box) && numel(inputs.bounding_box) == 6
        bounding_box = inputs.bounding_box;
        Xmin = bounding_box(1); Xmax = bounding_box(2);
        Ymin = bounding_box(3); Ymax = bounding_box(4);
        Zmin = bounding_box(5); Zmax = bounding_box(6);
    end
else
    % Each row of data in the file is read into a row in the output matrix
    meshLimits = fscanf(fileID, '%f %f %f', [3, 2])';
    fclose(fileID);

    % Assign values from the file
    Xmin = meshLimits(1, 1);  Xmax = meshLimits(2, 1);
    Ymin = meshLimits(1, 2);  Ymax = meshLimits(2, 2);
    Zmin = meshLimits(1, 3);  Zmax = meshLimits(2, 3);
end


% Or
% vert_coord = h5read(file_hdf5_mesh, '/vertices_coord'); % Read the HDF5 file information
% vert_coord_x_min = min(vert_coord(1,:));  vert_coord_x_max = max(vert_coord(1,:))  ;
% vert_coord_y_min = min(vert_coord(2,:));  vert_coord_y_max = max(vert_coord(2,:))  ;
% vert_coord_z_min = min(vert_coord(3,:));  vert_coord_z_max = max(vert_coord(3,:))  ;
% Xmin = min(vert_coord(1,:));  Xmax = max(vert_coord(1,:))  ;
% Ymin = min(vert_coord(2,:));  Ymax = max(vert_coord(2,:))  ;
% Zmin = min(vert_coord(3,:));  Zmax = max(vert_coord(3,:))  ;

switch crack_glob_or
    case 'XY'
        xmin = Xmin; ymin = Ymin; zmin = Zmin;
        xmax = Xmax; ymax = Ymax; zmax = Zmax;
    case 'YZ'
        xmin = Ymin; ymin = Zmin; zmin = Xmin;
        xmax = Ymax; ymax = Zmax; zmax = Xmax;
    case 'ZX'
        xmin = Zmin; ymin = Xmin; zmin = Ymin;
        xmax = Zmax; ymax = Xmax; zmax = Ymax;
end

% Plot Limits

xplim = xmin + (xmax - xmin) * [-0.1 1.1];
yplim = ymin + (ymax - ymin) * [-0.1 1.1];
zplim = zmin + (zmax - zmin) * [-0.1 1.1];

% Cracks
crack_full = h5read(file_hdf5,'/vs_broken_connect');



% Crack Vertices Initial Coordinates
crack_vert_coord_init_full = h5read(file_hdf5,'/v_elem_coord')';

% Amount of Cracks created at each Time Step

ncrack_per_timestep = h5read(file_hdf5,'/nSurfaces_per_time_step');



%%
% for ti = 60:60
% for ti = 50:n_time_steps

% Define the directory for mesh combination
mesh_combination = fullfile(rep_post, 'mesh_combination');

% Check if the directory exists
if ~exist(mesh_combination, 'dir')
    % If the directory does not exist, create it
    mkdir(mesh_combination);
end


% allFits = struct('ti',{},'cc',{},'nNodes',{},'xrange',{},'yrange',{}, ...
%                  'zfit_zmin',{},'zfit_zmax',{},'z_diff',{}, ...
%                  'fit_zmin',{},'fit_zmax',{},'gof_zmin',{},'gof_zmax',{}, ...
%                  'Af',{},'CMOD',{});
% allFitCount = 0;


for ti = ti_list
    crack_vert_coord_init_full_ti = crack_vert_coord_init_full;
    
    disp('####### Processing time step =  ' + string(ti) +' ###### ');
    crack_opening = h5read(file_hdf5,strcat('/crack_open_',num2str(ti,'%04d')));
    % Initialize your array and op_min value

    % Check if any value in the array is greater than op_min
    if all(crack_opening <= opmin)
        disp('##### WARNING - No crack openings larger than ' + string(opmin*1e9) + ' nm found at time step '+ string(ti) + ' ########');
        disp('####### Move to time step = ' + string(ti+1) +' ######');
        continue ;
    end


    % Crack Vertices Displacements
    crack_vert_disp = h5read(file_hdf5,strcat('/disp_',num2str(ti,'%04d')))';


    ncrack = ncrack_per_timestep(ti);
    disp('####### Start preparing the crack geometry at time step =  ' + string(ti) +' ###### ');
    if ncrack==0
        disp('####### WARNING - No cracks at ' + string(ti) +' time step ###### ');
        disp('####### Move to time step = ' + string(ti+1) +' ######');
        continue ;
        % return;
    end


    % Column swaps

    switch crack_glob_or
        case 'XY'
            disp('##### No column swapping ######');
        case 'YZ'
            disp('###### Column swapping ########');
            % crack_vert_coord_init_full = crack_vert_coord_init_full(:,[2,3,1]); % columns swap
            crack_vert_coord_init_full_ti = crack_vert_coord_init_full_ti(:,[2,3,1]); % columns swap
            crack_vert_disp = crack_vert_disp(:,[2,3,1]); % columns swap
        case 'ZX'
            disp('###### Column swapping ########');
            % crack_vert_coord_init_full = crack_vert_coord_init_full(:,[3,1,2]); % columns swap
            crack_vert_coord_init_full_ti = crack_vert_coord_init_full_ti(:,[3,1,2]);
            crack_vert_disp = crack_vert_disp(:,[3,1,2]); % columns swap
    end


    %% Creation of the coordinates of the two faces of the cracks
    % For each new micro-crack created, all its vertices are added twice to
    % |crack_vert_coord_init_full_ti| (once for each face).
    % A vertex belonging to n micro-cracks will thus appear 2n times in the array.


    % Reduce Crack Vertices Initial Coordinates to Unique Values

    [crack_vert_coord_init,i_cvcif,i_cvci] = unique(crack_vert_coord_init_full_ti,'rows');

    % Create the Middle, Bottom and Top Faces of Each Crack

    crack_vert_disp_mean = crack_vert_disp;
    crack_vert_disp_zmin = crack_vert_disp;
    crack_vert_disp_zmax = crack_vert_disp;

    for iv = 1:length(i_cvcif) % Loop on unified vertices

        % Displacement of each instance of a unified vertex
        crack_vert_disp_iv = crack_vert_disp(i_cvci==iv,:);

        % Average Displacement of the unified vertex
        disp_mean = mean(crack_vert_disp_iv,1);

        % Minimal Z displacement of the unified vertex
        % X and Y displacements are taken equal to the mean values

        disp_zmin = disp_mean;
        disp_zmin(:,3) = min(crack_vert_disp_iv(:,3));

        % Maximal Z displacement of the unified vertex
        % X and Y displacements are taken equal to the mean values

        disp_zmax = disp_mean;
        disp_zmax(:,3) = max(crack_vert_disp_iv(:,3));

        % Replace with the calculated displacements for all instances of the unified vertex,

        crack_vert_disp_mean(i_cvci==iv,:) = repmat(disp_mean,size(crack_vert_disp_iv,1),1);
        crack_vert_disp_zmin(i_cvci==iv,:) = repmat(disp_zmin,size(crack_vert_disp_iv,1),1);
        crack_vert_disp_zmax(i_cvci==iv,:) = repmat(disp_zmax,size(crack_vert_disp_iv,1),1);
    end

    % Reduce Crack Vertices Updated Coordinates to Unique Values

    crack_vert_coord_mean = crack_vert_coord_init + f_mag*crack_vert_disp_mean(i_cvcif,:);
    crack_vert_coord_zmin = crack_vert_coord_init + f_mag*crack_vert_disp_zmin(i_cvcif,:);
    crack_vert_coord_zmax = crack_vert_coord_init + f_mag*crack_vert_disp_zmax(i_cvcif,:);


    %% Storage of all edges constituting the cracks
    % Parsing of the |crack_full| array giving for each crack
    % the number of vertices and then the id of these vertices in order
    % and that once for each face


    % Counter for parsing

    read_count = 0;

    % A non-oriented edge is defined for each pair vert1(i) <-> vert2(i)
    vert1 = [];
    vert2 = [];

    for icrack = 1:ncrack % Loop on all the crack faces

        % First and last position to read the vertices constituting the crack

        start_pos = 2*icrack+1+read_count;
        stop_pos = start_pos + crack_full(start_pos-1) -1;

        % Update counter for parsing

        read_count = read_count + crack_full(start_pos-1);

        % Storage of the crack edges if its opening is superior to the threshold

        if crack_opening(icrack) >= opmin

            % Ordered list of unified vertices constituting the crack face
            % The numbering of the vertices starts at zero so an offset is necessary

            verti = i_cvci(crack_full(start_pos:stop_pos)+1);

            % For a triangular crack between vertices 1-2-3, we create two lists
            % 1-2-3 and 2-3-1 to obtain the edges 1<->2, 2<->3 and 3<->1

            vert1 = [vert1;verti]; %#ok<AGROW>
            vert2 = [vert2;circshift(verti,-1)]; %#ok<AGROW>

        end

    end

    if isempty(vert1)
        disp('###### WARNING - No cracks found at ' + string(opmin*1e9) +' nm  opening threshold at ' + string(ti) + ' time step #######');
        disp('###### Move to ' + string(ti+1) +' time step #######');
        disp('###### EXIT ###### ');
        continue ;
        % return;
    end
    %% Creation of the full graph
    % A graph is constructed from the vertices and edges of the cracks
    % Several simplifications are applied in order to keep only
    % the edges and vertices of the open cracks (according to threshold)


    % Construction of the full graph

    graph_crack_full = graph(vert1,vert2,1:length(vert1),'omitselfloops');

    % Simplification to remove non unique edges
    % Each edge is created at least twice (for each face of the crack)
    % and more if it belongs to several cracks

    graph_crack_full = simplify(graph_crack_full);

    % Associating the vertices of the graph with their coordinates

    graph_crack_full.Nodes.Name = string(1:size(graph_crack_full.Nodes,1))';

    X_gcf = crack_vert_coord_mean(1:size(graph_crack_full.Nodes,1),1);
    Y_gcf = crack_vert_coord_mean(1:size(graph_crack_full.Nodes,1),2);
    Z_gcf = crack_vert_coord_mean(1:size(graph_crack_full.Nodes,1),3);

    % Plot of the full graph with unique edges

    if full_graph
        figure('WindowState','maximized','Color',[1 1 1]);
        axes1 = axes;
        set(axes1, 'Color', 'w', 'FontName', 'Calibri', 'FontSize', 24, 'FontWeight', 'bold');
        hold(axes1, 'on');
        plot(graph_crack_full, ...
            'Parent', axes1, ...
            'ZData', Z_gcf, 'YData', Y_gcf, 'XData', X_gcf, ...
            'MarkerSize', 2, ...      % Larger points
            'LineWidth', 5, ...       % Thicker lines
            'EdgeColor', [1 0 0], ... % Red edges
            'NodeColor', [0 0 0], ... % Black nodes
            'EdgeLabel', {}, ...      % No edge labels
            'NodeLabel', {});         % No node labels

        title('Full Graph', 'FontWeight', 'bold', 'FontName', 'Calibri');
        view(axes1, [130.32, 37.22]);
        xlim(xplim); ylim(yplim); zlim(zplim);
        switch crack_glob_or
            case 'XY'
                xlabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                ylabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                zlabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
            case 'YZ'
                xlabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                ylabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                zlabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
            case 'ZX'
                xlabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                ylabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                zlabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
            otherwise
                warning('Unexpected value for crack_glob_or. No labels set.');
        end 
    axis(axes1, 'equal');
    box(axes1, 'on');
    hold(axes1, 'off');
    end

    % Simplification to remove non-connected vertices

    deg_graph_crack = degree(graph_crack_full);
    graph_crack = subgraph(graph_crack_full,deg_graph_crack>0);

    % Associating the vertices of the graph with their coordinates

    graph_crack_nodes = str2double(graph_crack.Nodes.Name);
    X_gc = crack_vert_coord_mean(graph_crack_nodes,1);
    Y_gc = crack_vert_coord_mean(graph_crack_nodes,2);
    Z_gc = crack_vert_coord_mean(graph_crack_nodes,3);

    % Plot of the simplified graph
    if simplified_graph
        figure('WindowState','maximized','Color',[1 1 1]);
        plot(graph_crack,'XData',X_gc,'YData',Y_gc,'ZData',Z_gc);
        title('Simplified Graph');
        xlim(xplim); ylim(yplim); zlim(zplim);
        switch crack_glob_or
            case 'XY'
                xlabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                ylabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                zlabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
            case 'YZ'
                xlabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                ylabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                zlabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
            case 'ZX'
                xlabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                ylabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                zlabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
            otherwise
                warning('Unexpected value for crack_glob_or. No labels set.');
        end 
    end

    %% Find all the connected components in crack graph
    % A connected component of a graph is a subgraph
    % in which each pair of nodes is connected with each other via a path.
    % A connected component of the graph thus corresponds to coalesced micro-cracks forming a marcro-crack


    % Initialize plot of the connected components
    if connected_components_graph
        figure('WindowState','maximized','Color',[1 1 1]);
        plot(graph_crack,'XData',X_gc,'YData',Y_gc,'ZData',Z_gc);
        title('Connected Components of Simplified Graph');
        view([130.32 37.22]);

        xlim([0.04 0.056]); ylim([0.0 0.02]); zlim(zplim);

        xlim(xplim); ylim(yplim); zlim(zplim);
        switch crack_glob_or
            case 'XY'
                xlabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                ylabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                zlabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
            case 'YZ'
                xlabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                ylabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                zlabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
            case 'ZX'
                xlabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                ylabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                zlabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
            otherwise
                warning('Unexpected value for crack_glob_or. No labels set.');
        end 
        hold on
    end

    % Compute the set of connected components of the graph

    [bin,binsize] = conncomp(graph_crack);

    % Descending ordered list of connected components with more than ncrack_comp cracks
    ncrack_comp = 10;
    disp('####### Check if there is any crack path contains more than ' +string(ncrack_comp) + ' microcracks ######"');

    are_any_greater = any(binsize > ncrack_comp);
    number_paths_greater = sum(binsize > ncrack_comp) ;

    if are_any_greater
        disp('##### ' + string(number_paths_greater) + ' crack paths were found contains more than ' + string(ncrack_comp) + ' microcracks######');
        disp('##### Extract the longest path #############');
    else
        disp('######No crack paths contains more than ' + string(ncrack_comp) + ' microcracks were found ######');
        disp('###### Move to ' + string(ti+1) +' time step #######');
        disp('###### EXIT ###### ');
        continue ;
    end

    [~,binsize_id,binsize_val] = find(binsize.*(binsize>ncrack_comp));
    [~,binsize_id_sort] = sort(binsize_val,'descend');
    cc_list=binsize_id(binsize_id_sort);

    % Creation of a structure for each connected component / macro-crack
    crack_comp = struct('cc',{},'idx',{},'graph',{},'nodes',{}, ...
                        'X_zmin',{},'Y_zmin',{},'Z_zmin',{}, ...
                        'X_zmax',{},'Y_zmax',{},'Z_zmax',{});

    for cc = cc_list

        crack_comp(cc).idx  = (bin == cc);
        crack_comp(cc).graph = subgraph(graph_crack, crack_comp(cc).idx);
        crack_comp(cc).nodes = str2double(crack_comp(cc).graph.Nodes.Name);

        crack_comp(cc).X_zmin = crack_vert_coord_zmin(crack_comp(cc).nodes,1);
        crack_comp(cc).Y_zmin = crack_vert_coord_zmin(crack_comp(cc).nodes,2);
        crack_comp(cc).Z_zmin = crack_vert_coord_zmin(crack_comp(cc).nodes,3);

        crack_comp(cc).X_zmax = crack_vert_coord_zmax(crack_comp(cc).nodes,1);
        crack_comp(cc).Y_zmax = crack_vert_coord_zmax(crack_comp(cc).nodes,2);
        crack_comp(cc).Z_zmax = crack_vert_coord_zmax(crack_comp(cc).nodes,3);

        % Optional plot
        if connected_components_graph
            if cc == cr_pa
                plot(crack_comp(cc).graph,'XData',crack_comp(cc).X_zmax,'YData',crack_comp(cc).Y_zmax,'ZData',crack_comp(cc).Z_zmax,...
                    'LineWidth',5,'EdgeColor','r','NodeColor','r');
            else
                plot(crack_comp(cc).graph,'XData',crack_comp(cc).X_zmax,'YData',crack_comp(cc).Y_zmax,'ZData',crack_comp(cc).Z_zmax,'LineWidth',5);
            end
        end
    end

    % Sort by number of nodes descending
    num_nodes = arrayfun(@(s) numel(s.nodes), crack_comp);
    [~, sorted_idx] = sort(num_nodes, 'descend');
    crack_comp = crack_comp(sorted_idx);

    if connected_components_graph
        axis equal;
        box on ; 
        hold off
    end
    % Identify non-empty subgraphs
    non_empty_idx = arrayfun(@(x) ~isempty(x.graph), crack_comp);
    
    % Filter the structure to retain only non-empty subgraphs
    crack_comp = crack_comp(non_empty_idx);
    
    % Get the number of nodes in each subgraph
    num_nodes = arrayfun(@(x) length(x.nodes), crack_comp);
    
    % Sort by number of nodes in descending order
    [~, sorted_idx] = sort(num_nodes, 'descend');
    
    % Apply sorting
    crack_comp = crack_comp(sorted_idx);


    %% Fit of two surfaces on the most connected component
    % Each face of the macro crack, defined as the most connected component,
    % is interpolated onto a surface. A smoothing is performed since
    % the numerical roughness is not representative but increases the complexity of the mesh.
    % These fitted surfaces are then used to generate a regular mesh of the macro-crack.

    % Store all fits for this time step (optional)
    % fits_this_ti = struct('ti',{},'cc',{},'nNodes',{}, ...
    %                     'xrange',{},'yrange',{}, ...
    %                     'zfit_zmin',{},'zfit_zmax',{},'z_diff',{}, ...
    %                     'fit_zmin',{},'fit_zmax',{}, ...
    %                     'gof_zmin',{},'gof_zmax',{}, ...
    %                     'Af',{},'CMOD',{});

    % fitCount = 0;


    % Fit options

    ft = fittype('loess');
    opts = fitoptions('Method','LowessFit');
    opts.Normalize = 'on';
    opts.Span = spa_smo;

    % inputs.fit.method    = 'loess';        % 'loess', 'lowess', 'poly23', 'poly33', 'smoothingspline'
    % inputs.fit.normalize = true;
    % inputs.fit.span      = spa_smo;        % only for loess/lowess
    % inputs.fit.robust    = 'Bisquare';     % 'Off', 'Bisquare', 'LAR'
    % inputs.fit.weights   = [];             % optional
    % inputs.fit.weights   =  crack_opening(crack_comp(cr_pa).idx);             % optional

    % [ft, opts] = build_fit_model(inputs.fit);


    % Loop over at most 3 components
    nComp = numel(crack_comp);


    if isempty(cr_pa)
        % Case 1: not provided → first min(3, nComp)
        cr_pa_list = 1:min(3, nComp);

    else
        % Case 2: user provided a list → use it as-is
        cr_pa_list = cr_pa(:).';   % force row vector

        % Safety check
        cr_pa_list = cr_pa_list(cr_pa_list >= 1 & cr_pa_list <= nComp);

        if isempty(cr_pa_list)
            error('cr_pa contains no valid component indices.');
        end
    end


    for cr_pai = cr_pa_list
        opts.Weights = [];

        % cc_id = crack_comp(cr_pai).cc;
        yrange_pre_min = crack_comp(cr_pai).Y_zmin ;
        xrange_pre_min = crack_comp(cr_pai).X_zmin ;
        z_pre_min = crack_comp(cr_pai).Z_zmin ;

        yrange_pre_max = crack_comp(cr_pai).Y_zmax ;
        xrange_pre_max = crack_comp(cr_pai).X_zmax ;
        z_pre_max = crack_comp(cr_pai).Z_zmax ;

        cropen_pre =  z_pre_max - z_pre_min ; 
        % fit.weights   =  cropen_pre ;

        % ---- zmin data ----
        [xD_zmin, yD_zmin, zD_zmin] = prepareSurfaceData(xrange_pre_min, yrange_pre_min, z_pre_min);

        % ---- zmax data ----
        [xD_zmax, yD_zmax, zD_zmax] = prepareSurfaceData(xrange_pre_max, yrange_pre_max, z_pre_max);

        % ---- crack_opening data ----
        [~, ~, wD_z] = prepareSurfaceData(xrange_pre_max, yrange_pre_max, cropen_pre);

        if numel(xD_zmin) <= 8 || numel(xD_zmax) <= 8
            disp("##### CC " + cr_pai + " skipped (not enough points) #####");
            continue;
        end

        % Add the crack openings as weights to the fitting
        wD_z(wD_z == 0) = eps;
        wD_z = wD_z / max(wD_z);

        k_zmin = convhull(xD_zmin, yD_zmin);
        xD_zmin = [xD_zmin; xD_zmin(k_zmin)]; %#ok<AGROW>
        yD_zmin = [yD_zmin; yD_zmin(k_zmin)]; %#ok<AGROW>
        zD_zmin = [zD_zmin; zD_zmin(k_zmin)]; %#ok<AGROW>

        opts.Weights = [wD_z; wD_z(k_zmin)];
        [fitresult_zmin, ~] = fit([xD_zmin, yD_zmin], zD_zmin, ft, opts);



        k_zmax = convhull(xD_zmax, yD_zmax);
        xD_zmax = [xD_zmax; xD_zmax(k_zmax)]; %#ok<AGROW>
        yD_zmax = [yD_zmax; yD_zmax(k_zmax)]; %#ok<AGROW>
        zD_zmax = [zD_zmax; zD_zmax(k_zmax)]; %#ok<AGROW>
        opts.Weights = [wD_z; wD_z(k_zmax)];

        [fitresult_zmax, ~] = fit([xD_zmax, yD_zmax], zD_zmax, ft, opts);

        % ---- grid ----
        dn_elem1 = (xmax - xmin) / spa_num;
        dn_elem2 = (ymax - ymin) / spa_num;
        dn_elem  = min(dn_elem1, dn_elem2);

        xmin1 = min([min(xD_zmin), min(xD_zmax)]);
        xmax1 = max([max(xD_zmin), max(xD_zmax)]);
        ymin1 = min([min(yD_zmin), min(yD_zmax)]);
        ymax1 = max([max(yD_zmin), max(yD_zmax)]);

        grid_span_x = max([10, ceil((xmax - xmin) / dn_elem)]);
        grid_span_y = max([10, ceil((ymax - ymin) / dn_elem)]);

        [xrange_i, yrange_i] = meshgrid(linspace(xmin, xmax, grid_span_x), ...
                                        linspace(ymin, ymax, grid_span_y));

        zfit_zmin_i = fitresult_zmin(xrange_i, yrange_i);
        zfit_zmax_i = fitresult_zmax(xrange_i, yrange_i);

        % Valid x/y indices inside the fitted domain
        ix_valid = find(xrange_i(1,:) >= xmin1 & xrange_i(1,:) <= xmax1);
        iy_valid = find(yrange_i(:,1) >= ymin1 & yrange_i(:,1) <= ymax1);

        ix_min = ix_valid(1);
        ix_max = ix_valid(end);
        iy_min = iy_valid(1);
        iy_max = iy_valid(end);

        inside_mask = ~(xrange_i < xmin1 | xrange_i > xmax1 | ...
                        yrange_i < ymin1 | yrange_i > ymax1);

        z_diff_i = zfit_zmax_i - zfit_zmin_i;   % opening from fit
        z_diff_i(~inside_mask) = 0;             % close crack outside


        % --- extend zmin first (solid reference) ---

        % X direction
        if ix_min > 1
            zfit_zmin_i(:, 1:ix_min-1) = repmat(zfit_zmin_i(:, ix_min), 1, ix_min-1);
        end

        if ix_max < size(zfit_zmin_i, 2)
            zfit_zmin_i(:, ix_max+1:end) = repmat( ...
                zfit_zmin_i(:, ix_max), ...
                1, size(zfit_zmin_i, 2) - ix_max );
        end

        % Y direction
        if iy_min > 1
            zfit_zmin_i(1:iy_min-1, :) = repmat( ...
                zfit_zmin_i(iy_min, :), ...
                iy_min-1, 1 );
        end

        if iy_max < size(zfit_zmin_i, 1)
            zfit_zmin_i(iy_max+1:end, :) = repmat( ...
                zfit_zmin_i(iy_max, :), ...
                size(zfit_zmin_i, 1) - iy_max, 1 );
        end





        zfit_zmax_i = zfit_zmin_i + z_diff_i;   % rebuild top surface


        % outside_mask =  xrange_i < xmin1 | xrange_i > xmax1 | yrange_i < ymin1 | yrange_i > ymax1;
        % inside_mask = ~outside_mask;

        % % --- Reference level (robust, physical) ---
        % z_ref = median(zfit_zmin_i(inside_mask), 'omitnan');

        % % Enforce flat surface outside
        % zfit_zmin_i(outside_mask) = z_ref;
        % zfit_zmax_i(outside_mask) = z_ref;

        % Handle NaN values
        % if any(isnan(zfit_zmin_i(:))) || any(isnan(zfit_zmax_i(:)))
        %     warning("NaN detected for CC " + cr_pai);
        %     % z_ref = mean(zfit_zmin_i, 'all', 'omitnan');
        %     zfit_zmin_i(isnan(zfit_zmin_i)) = z_ref;
        %     zfit_zmax_i(isnan(zfit_zmax_i)) = z_ref;
        % end

        % Clamp zero or negative openings to opmin
        if any(z_diff_i(:) < 0)
            disp("###### CC " + cr_pai + ": overlap detected, clamp to opmin ######");
            z_diff_i(z_diff_i < 0) = 0.0;
            zfit_zmax_i = z_diff_i + zfit_zmin_i;
        end
        z_diff_i = zfit_zmax_i - zfit_zmin_i;

        % Creation of the 4 sides to close the crack

        xside1 = [xrange_i(1,:);xrange_i(1,:)];
        yside1 = [yrange_i(1,:);yrange_i(1,:)];
        zside1 = [zfit_zmin_i(1,:);zfit_zmax_i(1,:)];


        xside2 = [xrange_i(end,:);xrange_i(end,:)];
        yside2 = [yrange_i(end,:);yrange_i(end,:)];
        zside2 = [zfit_zmin_i(end,:);zfit_zmax_i(end,:)];

        xside3 = [xrange_i(:,1) xrange_i(:,1)];
        yside3 = [yrange_i(:,1) yrange_i(:,1)];
        zside3 = [zfit_zmin_i(:,1) zfit_zmax_i(:,1)];

        xside4 = [xrange_i(:,end) xrange_i(:,end)];
        yside4 = [yrange_i(:,end) yrange_i(:,end)];
        zside4 = [zfit_zmin_i(:,end) zfit_zmax_i(:,end)];



        % ---- store everything ----
        % fitCount = fitCount + 1;
        % fits_this_ti(fitCount).ti       = ti;
        % fits_this_ti(fitCount).cc       = cr_pai;
        % fits_this_ti(fitCount).nNodes   = numel(crack_comp(cr_pai).nodes);

        % fits_this_ti(fitCount).xrange   = xrange_i;
        % fits_this_ti(fitCount).yrange   = yrange_i;
        % fits_this_ti(fitCount).zfit_zmin = zfit_zmin_i;
        % fits_this_ti(fitCount).zfit_zmax = zfit_zmax_i;
        % fits_this_ti(fitCount).z_diff   = z_diff_i;

        % fits_this_ti(fitCount).fit_zmin = fitresult_zmin;
        % fits_this_ti(fitCount).fit_zmax = fitresult_zmax;
        % fits_this_ti(fitCount).gof_zmin = gof_zmin;
        % fits_this_ti(fitCount).gof_zmax = gof_zmax;

        % fits_this_ti(fitCount).Af       = Af_i;
        % fits_this_ti(fitCount).CMOD     = CMOD_i;

        tag = sprintf('_ti%d_crpa%d_smfa%d_numsp%d_opmin%d', ...
        ti, cr_pai, round(spa_smo*100), spa_num, round(opmin*1e9));

        if ext_csv
            mesh_combination = fullfile(rep_post,'mesh_combination');
            if ~exist(mesh_combination,'dir'); mkdir(mesh_combination); end
            writematrix(zfit_zmin_i, fullfile(mesh_combination, ['zfit_zmin' tag '.csv']));
            writematrix(zfit_zmax_i, fullfile(mesh_combination, ['zfit_zmax' tag '.csv']));
            writematrix(yrange_i,    fullfile(mesh_combination, ['yrange' tag '.csv']));
            writematrix(xrange_i,    fullfile(mesh_combination, ['xrange' tag '.csv']));
        end % if ext_csv

        % Output to VTK (per connected component)
        if vtk_output
            switch crack_glob_or
                case 'XY'
                    vtkwrite(fullfile(mesh_combination, ['zfit_zmin'  tag '.vtk']), ...
                        'structured_grid', xrange_i, yrange_i, zfit_zmin_i, 'scalars', 'crack_opening', z_diff_i*1e6);
                    vtkwrite(fullfile(mesh_combination, ['zfit_zmax'  tag '.vtk']), ...
                        'structured_grid', xrange_i, yrange_i, zfit_zmax_i, 'scalars', 'crack_opening', z_diff_i*1e6);
                    vtkwrite(fullfile(mesh_combination, ['zfit_zmean' tag '.vtk']), ...
                        'structured_grid', xrange_i, yrange_i, (zfit_zmax_i+zfit_zmin_i)/2, 'scalars', 'crack_opening', z_diff_i*1e6);

                case 'YZ'
                    vtkwrite(fullfile(mesh_combination, ['zfit_zmin'  tag '.vtk']), ...
                        'structured_grid', zfit_zmin_i, xrange_i, yrange_i, 'scalars', 'crack_opening', z_diff_i*1e6);
                    vtkwrite(fullfile(mesh_combination, ['zfit_zmax'  tag '.vtk']), ...
                        'structured_grid', zfit_zmax_i, xrange_i, yrange_i, 'scalars', 'crack_opening', z_diff_i*1e6);
                    vtkwrite(fullfile(mesh_combination, ['zfit_zmean' tag '.vtk']), ...
                        'structured_grid', (zfit_zmax_i+zfit_zmin_i)/2, xrange_i, yrange_i, 'scalars', 'crack_opening', z_diff_i*1e6);

                case 'ZX'
                    vtkwrite(fullfile(mesh_combination, ['zfit_zmin'  tag '.vtk']), ...
                        'structured_grid', yrange_i, zfit_zmin_i, xrange_i, 'scalars', 'crack_opening', z_diff_i*1e6);
                    vtkwrite(fullfile(mesh_combination, ['zfit_zmax'  tag '.vtk']), ...
                        'structured_grid', yrange_i, zfit_zmax_i, xrange_i, 'scalars', 'crack_opening', z_diff_i*1e6);
                    vtkwrite(fullfile(mesh_combination, ['zfit_zmean' tag '.vtk']), ...
                        'structured_grid', yrange_i, (zfit_zmax_i+zfit_zmin_i)/2, xrange_i, 'scalars', 'crack_opening', z_diff_i*1e6);
            end
        end % if vtk_output

        % Output to STL (per connected component)
        if stl_outputs
            switch crack_glob_or
                case 'XY'
                    surf2stl(fullfile(mesh_combination, ['zfit_zmin'  tag '.stl']), xrange_i, yrange_i, zfit_zmin_i);
                    surf2stl(fullfile(mesh_combination, ['zfit_zmax'  tag '.stl']), xrange_i, yrange_i, zfit_zmax_i);
                    surf2stl(fullfile(mesh_combination, ['zfit_zmean' tag '.stl']), xrange_i, yrange_i, (zfit_zmax_i+zfit_zmin_i)/2);
                    surf2stl(fullfile(mesh_combination, ['side1' tag '.stl']), xside1, yside1, zside1);
                    surf2stl(fullfile(mesh_combination, ['side2' tag '.stl']), xside2, yside2, zside2);
                    surf2stl(fullfile(mesh_combination, ['side3' tag '.stl']), xside3, yside3, zside3);
                    surf2stl(fullfile(mesh_combination, ['side4' tag '.stl']), xside4, yside4, zside4);
                case 'YZ'
                    % same mapping as VTK 'YZ'
                    surf2stl(fullfile(mesh_combination, ['zfit_zmin'  tag '.stl']), zfit_zmin_i, xrange_i, yrange_i);
                    surf2stl(fullfile(mesh_combination, ['zfit_zmax'  tag '.stl']), zfit_zmax_i, xrange_i, yrange_i);
                    surf2stl(fullfile(mesh_combination, ['zfit_zmean' tag '.stl']), (zfit_zmax_i+zfit_zmin_i)/2, xrange_i, yrange_i);
                    surf2stl(fullfile(mesh_combination, ['side1' tag '.stl']), zside1, xside1, yside1);
                    surf2stl(fullfile(mesh_combination, ['side2' tag '.stl']), zside2, xside2, yside2);
                    surf2stl(fullfile(mesh_combination, ['side3' tag '.stl']), zside3, xside3, yside3);
                    surf2stl(fullfile(mesh_combination, ['side4' tag '.stl']), zside4, xside4, yside4);
                case 'ZX'
                    % same mapping as VTK 'ZX'
                    surf2stl(fullfile(mesh_combination, ['zfit_zmin'  tag '.stl']), yrange_i, zfit_zmin_i, xrange_i);
                    surf2stl(fullfile(mesh_combination, ['zfit_zmax'  tag '.stl']), yrange_i, zfit_zmax_i, xrange_i);
                    surf2stl(fullfile(mesh_combination, ['zfit_zmean' tag '.stl']), yrange_i, (zfit_zmax_i+zfit_zmin_i)/2, xrange_i);
                    surf2stl(fullfile(mesh_combination, ['side1' tag '.stl']), yside1, zside1, xside1);
                    surf2stl(fullfile(mesh_combination, ['side2' tag '.stl']), yside2, zside2, xside2);
                    surf2stl(fullfile(mesh_combination, ['side3' tag '.stl']), yside3, zside3, xside3);
                    surf2stl(fullfile(mesh_combination, ['side4' tag '.stl']), yside4, zside4, xside4);
            end
        end % if stl_outputs

    
        if crack_open_plot
            % Plotting
            figure('WindowState','maximized','Color',[1 1 1]);

            % Plot with X as vertical, Y as in-screen horizontal, Z as out-of-screen
            surf(zfit_zmax_i, yrange_i,xrange_i, z_diff_i * 1e6, 'EdgeColor', 'none');

            % Correct 3D view: make X vertical, Z horizontal, Y in-depth
            view([45, 20]);  % Azimuth, Elevation — adjust as needed
            camup([0 0 1]);   % Keep Z-up by convention
            clim([0 180]);
            % Axis limits
            xlim([Zmin Zmax]);
            zlim([Xmin Xmax]);
            ylim([Ymin Ymax]);


            axis equal;
            axis tight;

            % Colormap and colorbar
            colormap jet;
            cb = colorbar;
            cb.Label.String = 'Crack Opening (\mum)';
            cb.Label.Rotation = 0;
            cb.Label.Position(1) = cb.Label.Position(1) + 0.5;  % shift right
            cb.Label.FontSize = font_weight+4;
            cb.Label.FontWeight = 'bold';
            cb.FontSize = font_weight + 2;
            cb.TicksMode = 'auto';
            cb.Position = [0.6485 0.1272 0.0112 0.7842];  % [left bottom width height]
            colorbar('off')

            % Labels and title
            xlabel('X (m)', 'FontSize', font_weight+2, 'FontWeight', 'bold', 'Interpreter', 'tex');
            ylabel('Z (m)', 'FontSize', font_weight+2, 'FontWeight', 'bold', 'Interpreter', 'tex');
            zlabel('Y (m)', 'FontSize', font_weight+2, 'FontWeight', 'bold', 'Interpreter', 'tex');
            % title('Crack ppening Map (\mum)', 'FontSize', 20, 'FontWeight', 'bold', 'Interpreter', 'tex');

            % Axes styling
            set(gca, 'FontSize', font_weight+2, 'FontWeight', 'bold', 'LineWidth', line_width-1.5);



            box off;
            grid off;
            % shading interp;
            % lighting gouraud;
            % camlight headlight;

            paperWidth = 21.00;   % in cm
            paperHeight = 29.7;  % in cm
            
            % set(gcf,'Renderer','opengl')  % use OpenGL renderer for better shading

            set(gcf, 'Units', 'centimeters');
            set(gcf, 'Position', [0, 0, paperWidth, paperHeight]);  % match figure size
            
            set(gcf, 'PaperUnits', 'centimeters');
            set(gcf, 'PaperOrientation', 'landscape');
            set(gcf, 'PaperSize', [paperWidth, paperHeight]);
            set(gcf, 'PaperPositionMode', 'manual');
            set(gcf, 'PaperPosition', [0, 0, paperWidth, paperHeight]);  % fill page
            axtoolbar(gca, {});  % <- empty cell array disables it
    


            % Export the PDF exactly like Print Preview
            print(gcf, fullfile(mesh_combination,['side1' tag '.pdf']), '-dpdf','-fillpage');
            % === Profile at mid-surface (Y = middle slice) ===
            figure('WindowState','maximized','Color',[1 1 1]);
        
            mid_index = round(size(z_diff_i, 1) / 2);  % Y-direction is rows
        
            profile_x = yrange_i(:,mid_index);                      % X-axis (surface width)
            profile_y = z_diff_i(:,mid_index) * 1e6;  % Crack opening at mid Y
        
            plot(profile_x*1e3, profile_y, 'r-', 'LineWidth', line_width);
            xlabel('Position z (mm)', 'FontSize', font_weight+2, 'FontWeight', 'bold', 'Interpreter', 'tex');
            ylabel('Crack Opening (\mum)', 'FontSize',font_weight+2, 'FontWeight', 'bold', 'Interpreter', 'tex');
            title('BPM crack opening profile at mid-surface', 'FontSize', font_weight+6, 'FontWeight', 'bold','Interpreter', 'tex');
            grid on;
            ylim([0 (max(profile_y)+1e-6)*1.1]);  % Force Y-axis to start from zero
        
            set(gca, 'FontSize', font_weight, 'FontWeight', 'bold');
        end % if crack_open_plot

        if crack_surface_graph
            figure('WindowState','maximized','Color',[1 1 1]);
            surf(xrange_i,yrange_i,zfit_zmin_i,'FaceColor','r');
            hold on;
            surf(xrange_i,yrange_i,zfit_zmax_i,'FaceColor','b');
            surf(xside1,yside1,zside1);
            surf(xside2,yside2,zside2);
            surf(xside3,yside3,zside3);
            surf(xside4,yside4,zside4);
            hold off;

            title('Smoothed crack surfaces');
            xlim(xplim); ylim(yplim); zlim(zplim);
            switch crack_glob_or
                case 'XY'
                    xlabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                    ylabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                    zlabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                case 'YZ'
                    xlabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                    ylabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                    zlabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                case 'ZX'
                    xlabel('z (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                    ylabel('x (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                    zlabel('y (m)', 'FontWeight', 'bold', 'FontName', 'Calibri');
                otherwise
                    warning('Unexpected value for crack_glob_or. No labels set.');
            end 
        end % if crack_surface_graph



        if estimate_fracture_area
            % ---- sides (for area + CMOD) ----

            area1 = calculate_area_of_side(xside1, yside1, zside1);
            area2 = calculate_area_of_side(xside2, yside2, zside2);
            
            
            Af_i = (area1 + area2) / 2;

            mid = int64(size(zside1, 2)/2);
            CMOD1 = (zside1(2,mid) - zside1(1,mid) + zside1(2,mid+1) - zside1(1,mid+1)) / 2;
            CMOD2 = (zside2(2,mid) - zside2(1,mid) + zside2(2,mid+1) - zside2(1,mid+1)) / 2;
            CMOD_i = (CMOD1 + CMOD2) / 2;
            
            frac_area_file =fullfile(mesh_combination,['Af' tag '.csv']) ;
            CMOD_file =fullfile(mesh_combination,['CMOD' tag '.csv']) ;
            writematrix(Af_i,frac_area_file);
            writematrix(CMOD_i,CMOD_file);

        end % if estimate_fracture_area


        if tortousity_analysis

            x_min = Xmin;  x_max = Xmax;
            y_min =  Ymin;  y_max = Ymax;

            % --- ROI cut (do NOT overwrite xrange_i etc) ---
            x_idx = find(xrange_i(1,:) >= x_min & xrange_i(1,:) <= x_max);
            y_idx = find(yrange_i(:,1) >= y_min & yrange_i(:,1) <= y_max);

            if isempty(x_idx) || isempty(y_idx)
                disp("##### Tortuosity skipped: empty ROI for ti=" + ti + " cc=" + cr_pai + " #####");
            else
                xr   = xrange_i(y_idx, x_idx);
                yr   = yrange_i(y_idx, x_idx);
                zfit_max = zfit_zmax_i(y_idx, x_idx);
                zdif = z_diff_i(y_idx, x_idx);

                if size(zfit_max,1) < 2 || size(zfit_max,2) < 2
                    disp("##### Tortuosity skipped: ROI too small for ti=" + ti + " cc=" + cr_pai + " #####");
                else
                    % --- Tortuosity ---
                    [n, m] = size(zfit_max);
                    dimx = max(xr(:)) - min(xr(:));
                    dimy = max(yr(:)) - min(yr(:));

                    dx = dimx / (m - 1);
                    dy = dimy / (n - 1);

                    dz_x = diff(zfit_max, 1, 2);
                    surface_lengths_x = sum(sqrt(dz_x.^2 + dx^2), 2);
                    tortuosities_x = surface_lengths_x / ((m - 1) * dx);

                    dz_y = diff(zfit_max, 1, 1);
                    surface_lengths_y = sum(sqrt(dz_y.^2 + dy^2), 1);
                    tortuosities_y = surface_lengths_y / ((n - 1) * dy);

                    mean_tortuosity_x = mean(tortuosities_x, 'omitnan');
                    std_tortuosity_x  = std(tortuosities_x,  'omitnan');
                    mean_tortuosity_y = mean(tortuosities_y, 'omitnan');
                    std_tortuosity_y  = std(tortuosities_y,  'omitnan');

                    % --- Crack opening stats (use ROI) ---
                    e_mean = mean(zdif, 'all', 'omitnan');
                    e_std  = std(zdif,  0, 'all', 'omitnan');
                    e_min  = min(zdif, [], 'all', 'omitnan');
                    e_max  = max(zdif, [], 'all', 'omitnan');
                    % --- Hydraulic crack opening (flow along Y) ---
                    % Mean opening along transverse lines (X) at fixed Y
                    e_i = mean(zdif, 2, 'omitnan');   % [n x 1]

                    % Safety: remove invalid values
                    valid = e_i > 0 & isfinite(e_i);
                    e_i = e_i(valid);

                    % Cubic harmonic mean (hydraulic opening)
                    e_hyd = (1 / sum(1 ./ e_i.^3))^(1/3);


                    % --- Hydraulic-weighted statistics ---
                    w = 1 ./ e_i.^3;                 % hydraulic weights

                    % Weighted mean opening
                    e_hyd_mean = sum(w .* e_i) / sum(w);

                    % Weighted standard deviation
                    e_hyd_std = sqrt( sum(w .* (e_i - e_hyd_mean).^2) / sum(w) );

                    % --- Hurst ---
                    % [~, ~, zmax_mod, Pixww] = correctDEAPMatrices(xr, yr, zfit_max);
                    % [q_DEAP_max, C_DEAP_max, ~] = psd_2D(zmax_mod, Pixww);
                    % hurst_max = Hurst_fit(q_DEAP_max, C_DEAP_max, 0);


                    tort_file = fullfile(mesh_combination, ['tort_open_' tag '.txt']);
                    fileID = fopen(tort_file, 'w');
                    fprintf(fileID, 'Ty stdTy Tx stdTx emean stde emax emin ehyd ehyd_weighted stdehyd_weighted  \n');
                    fprintf(fileID, '%.6f %.6f %.6f %.6f %.17g %.17g %.17g %.17g %.17g %.17g %.17g\n', ...
                        mean_tortuosity_y, std_tortuosity_y, ...
                        mean_tortuosity_x, std_tortuosity_x, ...
                        e_mean, e_std, e_max, e_min, e_hyd, e_hyd_mean, e_hyd_std);
                    fclose(fileID);

                    % Optional console
                    % fprintf('ti=%d cc=%d | Ty=%.4f Tx=%.4f | e_mean=%.3f um | H=%.3f\n', ...
                    %     ti, cr_pai, mean_tortuosity_y, mean_tortuosity_x, e_mean*1e6, hurst_max.H);
                end % 
            end % if isempty(x_idx) || isempty(y_idx)
        end % if tortousity_analysis

    end % end loop on components

    % for k = 1:numel(fits_this_ti)
    %     allFitCount = allFitCount + 1;
    %     allFits(allFitCount) = fits_this_ti(k);
    % end


end % end loop on time steps



end % end function