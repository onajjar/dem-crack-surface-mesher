
function total_CMOD = calculate_CMOD_of_side(xside, yside, zside)
    % Determine if the side exists along the x-axis or y-axis
    is_x_axis_side = all(xside(:, 1) == xside(:, 2));
    is_y_axis_side = all(yside(:, 1) == yside(:, 2));

    % Compute the lengths of each line segment (base of the trapezoids)
    if is_x_axis_side
        disp('The side is on x_axis so CMOD is estimated from yside');
        CMOD = yside(1,int64(end/2));
        dx = 0;  % Side is along the x-axis, so dx is 0
        dy = diff(yside, 1, 2);
    elseif is_y_axis_side
        disp('The side is on y_axis so the hieght should be dx');
        dx = diff(xside, 1, 2);
        dy = 0;  % Side is along the y-axis, so dy is 0
    else
        error('The side should exist along either the x-axis or y-axis.');
    end

    % Compute the heights of the trapezoids
    dz = diff(zside, 1, 1);

    % Calculate the areas of the trapezoids using the trapezoidal rule
    areas = 0.5 * (dz(:, 1:end-1) + dz(:, 2:end)) .* (dx + circshift(dx, [0, -1]) + dy + circshift(dy, [0, -1]));

    % Sum up the areas to obtain the total area
    total_CMOD = sum(areas(:));
    
    disp('Total area of the side:');
    disp(total_CMOD);
end
