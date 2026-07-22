function [ft, opts] = build_fit_model(fit_in)
%BUILD_FIT_MODEL Create fittype and fitoptions safely

arguments
    fit_in.method    (1,:) char
    fit_in.normalize (1,1) logical = false
    fit_in.span      (1,1) double  = 0.2
    fit_in.robust    (1,:) char    = 'Off'
    fit_in.weights           = []
end

method = lower(fit_in.method);

switch method

    case {'loess','lowess'}
        ft = fittype(method);
        opts = fitoptions('Method','LowessFit');
        opts.Normalize = onoff(fit_in.normalize);
        opts.Span      = fit_in.span;

        % IMPORTANT: loess/lowess do NOT support robust options
        opts.Robust = 'Off';

    case {'poly11','poly12','poly22','poly23','poly33'}
        ft = fittype(method);
        opts = fitoptions(ft);
        opts.Normalize = onoff(fit_in.normalize);
        opts.Robust    = fit_in.robust;

    case 'smoothingspline'
        ft = fittype('smoothingspline');
        opts = fitoptions(ft);
        opts.Normalize = onoff(fit_in.normalize);
        opts.Robust    = fit_in.robust;

    otherwise
        error('Unsupported fit method: %s', fit_in.method);
end

% Optional weights
if ~isempty(fit_in.weights)
    opts.Weights = fit_in.weights;
end

end

% Helper
function s = onoff(tf)
    if tf, s = 'on'; else, s = 'off'; end
end
