param workspaceId string
param resourceName string

// This generic resource allows us to apply diagnostics to ANY resource type
resource diagnosticSetting 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
    name: '${resourceName}-logs'
    // No 'scope' here because we apply it when calling the module
    // scope: resourceGroup()
    properties: {
        workspaceId: workspaceId
        logs: [ {categoryGroup: 'allLogs', enabled: true} ]
        metrics: [ {category: 'AllMetrics', enabled: true} ]
    }
}