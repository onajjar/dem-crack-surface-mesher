
% Direct query of a 3D Delaunay triangulation created using
% delaunayTriangulation. Compute the free boundary as in Example 2
Points = rand(50,3);
dt = delaunayTriangulation(Points);
[tri, Xb] = freeBoundary(dt);
%Plot the surface mesh
trisurf(tri, Xb(:,1), Xb(:,2), Xb(:,3), 'FaceColor', 'cyan','FaceAlpha', 0.8);
