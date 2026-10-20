backendDirectory = fileparts(fileparts(mfilename('fullpath')));
addpath(backendDirectory);

classes = {
    'codesim.core.System'
    'codesim.core.Device'
    'codesim.core.RLGrid'
    'codesim.core.OutputJsonFactory'
    'codesim.core.SmallSignalAnalyzer'
    'codesim.systems.HybridSystem'
    'codesim.systems.VSGSMIBSystem'
    'codesim.systems.GFLLVRTSystem'
    'codesim.systems.ParallelVSGSystem'
    'codesim.systems.SGSMIBSystem'
    'codesim.systems.IEEE13System'
    'codesim.systems.CIGREMV14System'
    'codesim.components.Capacitor'
    'codesim.components.CPL'
    'codesim.components.GFLLongTerm'
    'codesim.components.GFLVSC'
    'codesim.components.InductionMotor'
    'codesim.components.Infbus'
    'codesim.components.PQLoad'
    'codesim.components.SG'
    'codesim.components.VSGCC'
    'codesim.components.VSGCCAVC'
    'codesim.components.VSGCL'
    'codesim.components.VSGLongTerm'
    'codesim.components.ZeroCurrent'
    'codesim.components.ZIP'
    };

for index = 1:numel(classes)
    className = classes{index};
    assert(~isempty(which(className)), 'Missing class: %s', className);
    assert(~isempty(meta.class.fromName(className)), ...
        'Invalid class: %s', className);
end

functions = {
    'codesim.api.Descriptor'
    'codesim.api.Runner'
    'codesim.api.SystemFactory'
    'codesim.core.fileHash'
    };
for index = 1:numel(functions)
    assert(~isempty(which(functions{index})), ...
        'Missing function: %s', functions{index});
end

fprintf('CodeSim_NAMESPACE_CHECK=OK classes=%d api=%d\n', ...
    numel(classes), numel(functions));
