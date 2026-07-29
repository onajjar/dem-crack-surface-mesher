% Fit options
% Compute effective crack opening for each unified vertex

ft = fittype('loess');
opts = fitoptions('Method', 'LowessFit');
opts.Normalize = 'on';
opts.Span = spa_smo; % control the smoothness of the surface

% Calculate weights based on crack opening
weights = crack_opening(crack_comp(cr_pa).idx);

% Fit of the zmin and zmax surfaces

% Prepare surface data
%% Fix for zmin
[xD_zmin, yD_zmin, zD_zmin] = prepareSurfaceData(crack_comp(cr_pa).X_zmin, crack_comp(cr_pa).Y_zmin, crack_comp(cr_pa).Z_zmin);

% Compute convex hull
k_zmin = convhull(xD_zmin, yD_zmin);
xD_zmin = [xD_zmin; xD_zmin(k_zmin)];
yD_zmin = [yD_zmin; yD_zmin(k_zmin)];
zD_zmin = [zD_zmin; zD_zmin(k_zmin)];
weights_zmin = [weights; weights(k_zmin)];

% Check if the number of data points is sufficient for fitting
if numel(xD_zmin) <= 8
    disp('##### Insufficient data. You need at least 8 data points to fit this model #####');
    disp('###### Move to ' + string(ti+1) +' time step #######');
    disp('###### EXIT ###### ');
    continue;
end

% Perform the fit with weights
opts.Weights = weights_zmin;
fitresult_zmin = fit([xD_zmin, yD_zmin], zD_zmin, ft, opts);

%% Fix for zmax
[xD_zmax, yD_zmax, zD_zmax] = prepareSurfaceData(crack_comp(cr_pa).X_zmax, crack_comp(cr_pa).Y_zmax, crack_comp(cr_pa).Z_zmax);

% Compute convex hull
k_zmax = convhull(xD_zmax, yD_zmax);
xD_zmax = [xD_zmax; xD_zmax(k_zmax)];
yD_zmax = [yD_zmax; yD_zmax(k_zmax)];
zD_zmax = [zD_zmax; zD_zmax(k_zmax)];
weights_zmax = [weights; weights(k_zmax)];

% Perform the fit with weights
opts.Weights = weights_zmax;
fitresult_zmax = fit([xD_zmax, yD_zmax], zD_zmax, ft, opts);
