var myUserObjectId = '7d89d7bb-1f79-4ed4-bf0a-e82c59a8f91b'

// Parameters for flexibility across regions
param location string = resourceGroup().location
param openAiName string = 'openai-${uniqueString(resourceGroup().id)}'
param searchName string = 'search-${uniqueString(resourceGroup().id)}'

@description('Storage account name for SEC blob data and Function runtime storage (must be globally unique, 3-24 lowercase alphanumeric).')
param storageAccountName string = 'st${uniqueString(resourceGroup().id)}'

@description('Blob container that holds SEC filing artifacts.')
param blobContainerName string = 'sec-filings'

@description('Optional object ID for a future Function App managed identity that should also write blobs.')
param futureFunctionPrincipalObjectId string = ''

@description('Azure Function App name for SEC processing pipeline.')
param functionAppName string = 'func-sec-${uniqueString(resourceGroup().id)}'

@description('Hosting plan name for the Azure Function App.')
param functionPlanName string = 'plan-sec-${uniqueString(resourceGroup().id)}'

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

resource kvRoleAssignmentMe 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, myUserObjectId, 'Key Vault Secrets Officer')
  scope: keyVault
  properties: {
    // This GUID is the built-in ID for "Key Vault Secrets Officer"
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7')
    principalId: myUserObjectId
    principalType: 'User' 
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


// 5b. Azure Storage Account for SEC blobs and future Function runtime state.
// Security defaults: HTTPS only, TLS 1.2 minimum, and no anonymous/public blob access.
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    accessTier: 'Hot'
  }
}

// 5c. Blob service configuration under the storage account.
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    isVersioningEnabled: true
  }
}

// 5d. Managed blob container used by the ingestion pipeline.
resource secFilingsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: blobContainerName
  properties: {
    publicAccess: 'None'
  }
}


// 5e. Grant the existing project managed identity permission to read/write blobs.
resource blobRoleAssignmentProjectIdentity 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, projectIdentity.id, 'Storage Blob Data Contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: projectIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// 5f. Optionally grant a future Function App identity the same blob data permissions.
resource blobRoleAssignmentFunctionIdentity 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(futureFunctionPrincipalObjectId)) {
  name: guid(storageAccount.id, futureFunctionPrincipalObjectId, 'Storage Blob Data Contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: futureFunctionPrincipalObjectId
    principalType: 'ServicePrincipal'
  }
}

resource functionPlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: functionPlanName
  location: location
  kind: 'linux'
  sku: {
    tier: 'Dynamic'
    name: 'Y1'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: functionPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      appSettings: [
        {
          name: 'AzureWebJobsStorage'
          value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'WEBSITE_RUN_FROM_PACKAGE'
          value: '1'
        }
        {
          name: 'BLOB_ACCOUNT_URL'
          value: storageAccount.properties.primaryEndpoints.blob
        }
        {
          name: 'BLOB_CONTAINER_NAME'
          value: blobContainerName
        }
        {
          name: 'SEC_COMPANY_NAME'
          value: 'EnergyAI-Research'
        }
        {
          name: 'SEC_EMAIL'
          value: 'scarredentos@gmail.com'
        }
        {
          name: 'SEC_HTML_QUEUE_NAME'
          value: 'sec-html-jobs'
        }
        {
          name: 'SEC_PDF_QUEUE_NAME'
          value: 'sec-pdf-jobs'
        }
        {
          name: 'DOC_INTEL_ENDPOINT'
          value: docIntelligence.properties.endpoint
        }
        {
          name: 'DOC_INTEL_KEY'
          value: '@Microsoft.KeyVault(SecretUri=${docIntelligenceSecret.properties.secretUriWithVersion})'
        }
      ]
    }
  }
}

resource blobRoleAssignmentFunctionAppIdentity 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, 'Storage Blob Data Contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource queueRoleAssignmentFunctionAppIdentity 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, functionApp.id, 'Storage Queue Data Contributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '974c5e8b-45b9-4653-ba55-5f855dd0fb88')
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource keyVaultSecretsRoleAssignmentFunctionAppIdentity 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, functionApp.id, 'Key Vault Secrets User')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// New parameter for document intelligence.
param docIntelligenceName string = 'docint-${uniqueString(resourceGroup().id)}'

// 6. Azure AI Document Intelligence Service
resource docIntelligence 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
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

// Storage account-level telemetry for capacity/transaction monitoring.
resource storageAccountDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${storageAccount.name}-diag'
  scope: storageAccount
  properties: {
    workspaceId: logAnalytics.id
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

// Blob service diagnostics for operation logging (read/write/delete) and metrics.
resource blobServiceDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${storageAccount.name}-blob-diag'
  scope: blobService
  properties: {
    workspaceId: logAnalytics.id
    logs: [
      { category: 'StorageRead', enabled: true }
      { category: 'StorageWrite', enabled: true }
      { category: 'StorageDelete', enabled: true }
    ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}


output openAiEndpoint string = openAiAccount.properties.endpoint
output searchEndpoint string = 'https://${searchName}.search.windows.net'
output docIntelligenceEndpoint string = docIntelligence.properties.endpoint
output storageAccountNameOut string = storageAccount.name
output blobAccountUrl string = storageAccount.properties.primaryEndpoints.blob
output blobContainerNameOut string = secFilingsContainer.name
output functionAppNameOut string = functionApp.name
