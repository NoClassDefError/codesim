backendDirectory = fileparts(fileparts(mfilename('fullpath')));
addpath(backendDirectory);
outputDirectory = fullfile(backendDirectory, 'codegen');

systems = [
    "HybridSystem"
    "VSGSMIBSystem"
    "GFLLVRTSystem"
    "ParallelVSGSystem"
    "SGSMIBSystem"
    "IEEE13System"
    "CIGREMV14System"
    ];

for index = 1:numel(systems)
    systemName = systems(index);
    [snapshotFile, descriptor] = codesim.api.Descriptor( ...
        systemName, struct(), struct());
    assert(isfile(snapshotFile), ...
        'Descriptor did not create a snapshot for %s.', systemName);
    assert(string(fileparts(snapshotFile)) == string(outputDirectory), ...
        'Descriptor wrote outside codegen for %s.', systemName);
    assert(~isempty(descriptor.components), ...
        'Descriptor returned no components for %s.', systemName);
    assert(startsWith(string(descriptor.system.className), ...
        "codesim.systems."), ...
        'Descriptor returned the old namespace for %s.', systemName);
    fprintf('CodeSim_DESCRIPTOR_CHECK=OK system=%s components=%d\n', ...
        systemName, numel(descriptor.components));
end
