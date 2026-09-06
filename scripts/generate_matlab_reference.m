function generate_matlab_reference(output_root)
%GENERATE_MATLAB_REFERENCE Run the unchanged legacy MATLAB against frozen inputs.
% Outputs are written beneath output_root, never into the frozen fixtures.
% Requires MATLAB and Curve Fitting Toolbox. Run from the repository with:
% addpath('scripts'); generate_matlab_reference('path/to/new/output');

source_root = fileparts(mfilename('fullpath'));
if nargin < 1 || isempty(output_root)
    output_root = fullfile(fileparts(source_root), '_runtime', 'live_matlab_oracle');
end
if ~exist(output_root, 'dir'), mkdir(output_root); end
repo = fileparts(source_root);
legacy = fullfile(repo, 'legacy', 'matlab');
input_dir = fullfile(repo, 'tests', 'data', 'matlab_r2025b', 'inputs');
raw_dir = fullfile(output_root, 'raw');
work_dir = fullfile(output_root, 'work');
deap_input_dir = fullfile(work_dir, 'deap_inputs');
deap_output_dir = fullfile(work_dir, 'matlab_deap_outputs');
deap_log_dir = fullfile(work_dir, 'matlab_deap_logs');

% The legacy function writes mesh_combination even with exports disabled.
% Copy only input files into the requested output directory before calling it.
case_names = {'1_simple', '2_large', '3_rebar', '4_brazilian'};
input_names = {'deap_post.h5', 'deap_output.h5', 'input.boundary'};
for ci = 1:numel(case_names)
    destination = fullfile(deap_input_dir, case_names{ci});
    if ~exist(destination, 'dir'), mkdir(destination); end
    for fi = 1:numel(input_names)
        source = fullfile(repo, 'examples', 'deap', case_names{ci}, 'results', input_names{fi});
        if isfile(source), copyfile(source, fullfile(destination, input_names{fi})); end
    end
end

addpath(legacy);
if ~exist(raw_dir, 'dir'), mkdir(raw_dir); end
if ~exist(deap_output_dir, 'dir'), mkdir(deap_output_dir); end
if ~exist(deap_log_dir, 'dir'), mkdir(deap_log_dir); end
set(groot, 'defaultFigureVisible', 'off');
close all force;

runtime = struct();
runtime.matlab_version = version;
runtime.matlab_release = version('-release');
curvefit_version = ver('curvefit');
if isempty(curvefit_version)
    error('Curve Fitting Toolbox is required for the oracle run.');
end
runtime.curve_fitting_toolbox = curvefit_version.Version;
runtime.computer = computer;
runtime.started_utc = char(datetime('now', 'TimeZone', 'UTC', 'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z'''));

fprintf('MATLAB_ORACLE_START %s\n', runtime.started_utc);
fprintf('MATLAB_VERSION %s\n', runtime.matlab_version);
fprintf('CURVE_FITTING_TOOLBOX %s\n', runtime.curve_fitting_toolbox);

run_deap_cases(source_root, input_dir, raw_dir, deap_input_dir, deap_output_dir, deap_log_dir, runtime);
run_arbitrary_cases(input_dir, raw_dir, runtime);
run_contact_cases(input_dir, raw_dir, runtime);

runtime.completed_utc = char(datetime('now', 'TimeZone', 'UTC', 'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z'''));
write_json(fullfile(raw_dir, 'matlab_runtime.json'), runtime);
marker = fopen(fullfile(raw_dir, 'matlab_oracle_complete.txt'), 'w');
fprintf(marker, 'completed_utc=%s\n', runtime.completed_utc);
fclose(marker);
fprintf('MATLAB_ORACLE_COMPLETE %s\n', runtime.completed_utc);
end


function run_deap_cases(root, input_dir, raw_dir, deap_input_dir, deap_output_dir, deap_log_dir, runtime)
scenario_text = fileread(fullfile(input_dir, 'deap_scenarios.json'));
scenarios = jsondecode(scenario_text);
count = numel(scenarios);
manifest = repmat(struct( ...
    'id', '', ...
    'source_case', '', ...
    'status', '', ...
    'elapsed_seconds', NaN, ...
    'output', '', ...
    'log', '', ...
    'error_identifier', '', ...
    'error_message', ''), count, 1);

for index = 1:count
    scenario = scenarios(index);
    scenario_id = char(scenario.id);
    source_case = char(scenario.source_case);
    case_dir = fullfile(deap_input_dir, source_case);
    time_step = double(scenario.time_step);
    component = double(scenario.component);
    span = double(scenario.span);
    grid_resolution = double(scenario.grid_resolution);
    opening_threshold = double(scenario.opening_threshold);
    orientation = char(scenario.orientation);
    magnification = double(scenario.magnification);
    bounding_box = scenario.bounding_box;
    output_path = fullfile(deap_output_dir, [scenario_id '.mat']);
    log_path = fullfile(deap_log_dir, [scenario_id '.log']);

    manifest(index).id = scenario_id;
    manifest(index).source_case = source_case;
    manifest(index).output = output_path;
    manifest(index).log = log_path;
    fprintf('MATLAB_DEAP %02d/%02d %s\n', index, count, scenario_id);
    started = tic;
    try
        if isempty(bounding_box)
            transcript = evalc(['[xrange_i, yrange_i, zfit_zmax_i, zfit_zmin_i] = ' ...
                'DEAP_crack_CFD_coupling(case_dir, ' ...
                '''time_step'', time_step, ''cr_pa'', component, ' ...
                '''spa_smo'', span, ''spa_num'', grid_resolution, ' ...
                '''opmin'', opening_threshold, ''crack_glob_or'', orientation, ' ...
                '''f_mag'', magnification, ''full_graph'', false, ' ...
                '''simplified_graph'', false, ''connected_components_graph'', false, ' ...
                '''crack_surface_graph'', false, ''crack_open_plot'', false, ' ...
                '''vtk_output'', false, ''stl_outputs'', false, ''ext_csv'', false, ' ...
                '''run_mesher'', false, ''estimate_fracture_area'', false, ' ...
                '''tortousity_analysis'', false);']);
        else
            bounding_box = double(bounding_box(:).');
            transcript = evalc(['[xrange_i, yrange_i, zfit_zmax_i, zfit_zmin_i] = ' ...
                'DEAP_crack_CFD_coupling(case_dir, ' ...
                '''time_step'', time_step, ''cr_pa'', component, ' ...
                '''spa_smo'', span, ''spa_num'', grid_resolution, ' ...
                '''opmin'', opening_threshold, ''crack_glob_or'', orientation, ' ...
                '''f_mag'', magnification, ''bounding_box'', bounding_box, ' ...
                '''full_graph'', false, ''simplified_graph'', false, ' ...
                '''connected_components_graph'', false, ''crack_surface_graph'', false, ' ...
                '''crack_open_plot'', false, ''vtk_output'', false, ' ...
                '''stl_outputs'', false, ''ext_csv'', false, ''run_mesher'', false, ' ...
                '''estimate_fracture_area'', false, ''tortousity_analysis'', false);']);
        end
        elapsed_seconds = toc(started);
        save(output_path, 'xrange_i', 'yrange_i', 'zfit_zmin_i', 'zfit_zmax_i', ...
            'elapsed_seconds', 'scenario_id', '-v7');
        write_text(log_path, transcript);
        manifest(index).status = 'ok';
        manifest(index).elapsed_seconds = elapsed_seconds;
    catch exception
        elapsed_seconds = toc(started);
        manifest(index).status = 'error';
        manifest(index).elapsed_seconds = elapsed_seconds;
        manifest(index).error_identifier = exception.identifier;
        manifest(index).error_message = exception.message;
        diagnostic = getReport(exception, 'extended', 'hyperlinks', 'off');
        write_text(log_path, diagnostic);
        fprintf('MATLAB_DEAP_ERROR %s %s\n', scenario_id, exception.message);
    end
    close all force;
end

deap_manifest = struct();
deap_manifest.runtime = runtime;
deap_manifest.driver = fullfile(root, 'generate_matlab_reference.m');
deap_manifest.legacy_function = which('DEAP_crack_CFD_coupling');
deap_manifest.cases = manifest;
write_json(fullfile(raw_dir, 'matlab_deap_manifest.json'), deap_manifest);
end


function run_arbitrary_cases(input_dir, raw_dir, runtime)
data = load(fullfile(input_dir, 'arbitrary_inputs.mat'));
count = numel(data.case_ids);
predictions = cell(1, count);
successes = false(1, count);
errors = cell(1, count);
warning_messages = cell(1, count);
elapsed_seconds = nan(1, count);

ft = fittype('loess');
for index = 1:count
    case_id = cell_text(data.case_ids{index});
    fprintf('MATLAB_ARBITRARY %03d/%03d %s\n', index, count, case_id);
    started = tic;
    lastwarn('');
    try
        x = double(data.xs{index}(:));
        y = double(data.ys{index}(:));
        z = double(data.zs{index}(:));
        qx = double(data.qxs{index});
        qy = double(data.qys{index});
        user_weights = double(data.weights{index}(:));
        opts = fitoptions('Method', 'LowessFit');
        opts.Normalize = 'on';
        opts.Span = double(data.spans(index));
        opts.Weights = user_weights;
        [fit_result, ~] = fit([x, y], z, ft, opts);
        predictions{index} = fit_result(qx, qy);
        successes(index) = true;
        errors{index} = '';
    catch exception
        predictions{index} = [];
        successes(index) = false;
        errors{index} = sprintf('%s: %s', exception.identifier, exception.message);
        fprintf('MATLAB_ARBITRARY_ERROR %s %s\n', case_id, exception.message);
    end
    [warning_message, ~] = lastwarn;
    warning_messages{index} = warning_message;
    elapsed_seconds(index) = toc(started);
end

save(fullfile(raw_dir, 'matlab_arbitrary_outputs.mat'), ...
    'predictions', 'successes', 'errors', 'warning_messages', ...
    'elapsed_seconds', 'runtime', '-v7');
end


function run_contact_cases(input_dir, raw_dir, runtime)
data = load(fullfile(input_dir, 'contact_inputs.mat'));
count = numel(data.case_ids);
raw_lowers = cell(1, count);
raw_uppers = cell(1, count);
final_uppers = cell(1, count);
successes = false(1, count);
errors = cell(1, count);
warning_messages = cell(1, count);
elapsed_seconds = nan(1, count);

ft = fittype('loess');
for index = 1:count
    case_id = cell_text(data.case_ids{index});
    fprintf('MATLAB_CONTACT %02d/%02d %s\n', index, count, case_id);
    started = tic;
    lastwarn('');
    try
        x = double(data.xs{index}(:));
        y = double(data.ys{index}(:));
        zmin = double(data.zmins{index}(:));
        zmax = double(data.zmaxs{index}(:));
        qx = double(data.qxs{index});
        qy = double(data.qys{index});
        user_weights = double(data.weights{index}(:));
        opts = fitoptions('Method', 'LowessFit');
        opts.Normalize = 'on';
        opts.Span = double(data.spans(index));
        opts.Weights = user_weights;
        [fit_lower, ~] = fit([x, y], zmin, ft, opts);
        [fit_upper, ~] = fit([x, y], zmax, ft, opts);
        raw_lower = fit_lower(qx, qy);
        raw_upper = fit_upper(qx, qy);
        raw_opening = raw_upper - raw_lower;
        clamped_opening = raw_opening;
        clamped_opening(clamped_opening < 0.0) = 0.0;
        final_upper = raw_lower + clamped_opening;
        raw_lowers{index} = raw_lower;
        raw_uppers{index} = raw_upper;
        final_uppers{index} = final_upper;
        successes(index) = true;
        errors{index} = '';
    catch exception
        raw_lowers{index} = [];
        raw_uppers{index} = [];
        final_uppers{index} = [];
        successes(index) = false;
        errors{index} = sprintf('%s: %s', exception.identifier, exception.message);
        fprintf('MATLAB_CONTACT_ERROR %s %s\n', case_id, exception.message);
    end
    [warning_message, ~] = lastwarn;
    warning_messages{index} = warning_message;
    elapsed_seconds(index) = toc(started);
end

save(fullfile(raw_dir, 'matlab_contact_outputs.mat'), ...
    'raw_lowers', 'raw_uppers', 'final_uppers', 'successes', 'errors', ...
    'warning_messages', 'elapsed_seconds', 'runtime', '-v7');
end


function value = cell_text(input_value)
value = input_value;
while iscell(value)
    value = value{1};
end
value = char(value);
end


function write_text(path, value)
handle = fopen(path, 'w');
if handle == -1
    error('Cannot open %s for writing.', path);
end
cleanup = onCleanup(@() fclose(handle));
fprintf(handle, '%s', value);
clear cleanup;
end


function write_json(path, value)
text = jsonencode(value, 'PrettyPrint', true);
write_text(path, [text newline]);
end
