function valid = check_valid_point(point, center1, center2, radius, threshold)
    % Find the projection of point onto the line defined by center1 and center2
    v = point - center1;
    u = center2 - center1;
    projection = center1 + dot(v, u) / dot(u, u) * u;
    % Check distance between projection and point
    distance = norm(projection - point);
    valid = (distance > radius + threshold);
end