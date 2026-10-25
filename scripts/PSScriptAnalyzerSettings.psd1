@{
    Severity     = @('Error', 'Warning', 'Information')
    ExcludeRules = @(
        # The scripts are interactive console installers; Write-Host is intended.
        'PSAvoidUsingWriteHost',
        # Helper names read naturally in the scripts; they are not exported cmdlets.
        'PSUseApprovedVerbs',
        'PSUseSingularNouns',
        'PSUseShouldProcessForStateChangingFunctions'
    )
    Rules        = @{
        PSUseCompatibleSyntax = @{
            Enable         = $true
            TargetVersions = @('5.1')
        }
    }
}
