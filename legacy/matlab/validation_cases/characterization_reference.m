function characterization_reference(output_path)
%CHARACTERIZATION_REFERENCE Independent analytical checks for Python metrics.
% This compact validation does not invoke the ambiguous legacy roughness/PSD
% scripts. It evaluates definitions that can be checked directly.

if nargin < 1
    output_path = fullfile('docs', 'validation', ...
        'matlab-characterization-reference.json');
end

constant_aperture = 2.0e-4;
planar = struct();
planar.arithmetic_mean_aperture = mean(repmat(constant_aperture, 1, 25));
planar.cubic_mean_aperture = mean(repmat(constant_aperture, 1, 25).^3)^(1/3);
planar.equivalent_aperture = ...
    mean(1 ./ repmat(constant_aperture, 1, 25).^3)^(-1/3);
planar.geometrical_tortuosity = 1.0;
planar.aperture_standard_deviation_population = ...
    std(repmat(constant_aperture, 1, 25), 1);

x = linspace(0.0, 1.2, 31);
b = 1.0e-4 + 2.0e-4 * x / (x(end) - x(1));
dx = diff(x);
trapezoidal_resistance = sum(dx .* 0.5 .* ...
    (b(1:end-1).^(-3) + b(2:end).^(-3)));
varying = struct();
varying.projected_length = x(end) - x(1);
varying.series_resistance_integral = trapezoidal_resistance;
varying.equivalent_aperture = ...
    (trapezoidal_resistance / varying.projected_length)^(-1/3);
varying.arithmetic_mean_aperture = mean(b);
varying.cubic_mean_aperture = mean(b.^3)^(1/3);

reference = struct();
reference.software = version;
reference.definition = [ ...
    'Cubic-law resistance integrated by the trapezoidal rule; ', ...
    'population statistics used for deterministic comparison.' ...
];
reference.planar_constant = planar;
reference.varying_aperture = varying;

parent = fileparts(output_path);
if ~isempty(parent) && ~isfolder(parent)
    mkdir(parent);
end
file_id = fopen(output_path, 'w');
if file_id < 0
    error('Could not open output path: %s', output_path);
end
cleanup = onCleanup(@() fclose(file_id));
fprintf(file_id, '%s\n', jsonencode(reference, PrettyPrint=true));
end
