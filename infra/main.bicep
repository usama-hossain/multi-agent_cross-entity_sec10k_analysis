// Parameters for flexibility across regions
param location string = resourceGroup().location
param openAiName string = 'openai-${uniqueString(resourceGroup().id)}'
param searchName string = 'search-${uniqueString(resourceGroup().id)}'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: 'utilites-project-logAnalytics'
  location: location
  properties: { sku: { name: 'PerGB2018' } }
}

// 1. Azure OpenAI Service
resource openAiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: openAiName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: openAiName
    publicNetworkAccess: 'Enabled'
  }
}

// 2. Azure AI Search Service
resource searchService 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchName
  location: location
  sku: {
    name: 'basic'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
  }
}

// 3. Create the 'Identity Card' (User assigned managed identity)
resource projectIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'project1-id'
  location: location
}

// 4. Create the 'Safe' (Key Vault) with RBAC Enabled
resource keyVault 'Microsoft.KeyVault/vaults@2023-02-01' = {
  name: 'kv-utility-${uniqueString(resourceGroup().id)}'
  location: location
  properties: {
    sku: {family: 'A', name:'standard'}
    tenantId: subscription().tenantId
    enableRbacAuthorization: true // This allows us to use role assignments instead of legacy policies
    enabledForTemplateDeployment: true
  }
}

// 5. The 'Glue' (Role Assignment): Granting the identity access to the Vault
resource kvRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, projectIdentity.id, 'Key Vault Secrets User')
  scope: keyVault
  properties: {
    // This is the specific GUID for the "Key Vault Secrets User" built-in role
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: projectIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// New parameter for document intelligence.
param docIntelligenceName string = 'docint-${uniqueString(resourceGroup().id)}'

// 6. Azure AI Document Intelligence Service
resource docIntelligence 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: docIntelligenceName
  location: location
  kind: 'FormRecognizer' // This is the 'kind' for Document Intelligence
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: docIntelligenceName
    publicNetworkAccess: 'Enabled'
  }
}

// 7. Store the Document Intelligence API key in Key Vault as a secret
resource docIntelligenceSecret 'Microsoft.KeyVault/vaults/secrets@2023-02-01' = {
  parent: keyVault
  name: 'DocIntelligenceApiKey'
  properties: {
    value: docIntelligence.listKeys().key1 // This retrieves the API key from the Document Intelligence resource we just created
  }
}

// --- Diagnostics inline ---

resource openAiDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'openAi-diag'
  scope: openAiAccount
  properties: {
    workspaceId: logAnalytics.id
    logs: [ {categoryGroup: 'allLogs', enabled: true} ]
    metrics: [ {category: 'AllMetrics', enabled: true} ]
  }
}

resource searchDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${searchName}-diag'
  scope: searchService
  properties: {
    workspaceId: logAnalytics.id
    logs: [ { categoryGroup: 'allLogs', enabled: true } ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

resource kvDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${keyVault.name}-diag'
  scope: keyVault
  properties: {
    workspaceId: logAnalytics.id
    logs: [ { categoryGroup: 'audit', enabled: true } ]
  }
}


output openAiEndpoint string = openAiAccount.properties.endpoint
output searchEndpoint string = 'https://${searchName}.search.windows.net'
output docIntelligenceEndpoint string = docIntelligence.properties.endpoint
