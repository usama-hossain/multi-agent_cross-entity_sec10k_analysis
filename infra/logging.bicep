param workspaceId string
param resourceName string
param resourceType string

// 1. Reference the existing resource we want to monitor
// This bridges the module to the specific OpenAI/Search/KV resource
resource targetResource 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' existing = {
    name: resourceName
}

// 2. Apply the diagnostic setting using the 'scope' property internally
// This generic resource allows us to apply diagnostics to ANY resource type
resource diagnosticSetting 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
    name: '${resourceName}-logs'
    scope: targetResource
    properties: {
        workspaceId: workspaceId
        logs: [ {categoryGroup: 'allLogs', enabled: true} ]
        metrics: [ {category: 'AllMetrics', enabled: true} ]
    }
}