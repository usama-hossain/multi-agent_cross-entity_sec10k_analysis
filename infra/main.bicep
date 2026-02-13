// Parameters for flexibility across regions
param location string = resourceGroup().location
param openAiName string = 'openai-${uniqueString(resourceGroup().id)}'
param searchName string = 'search-${uniqueString(resourceGroup().id)}'

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

// 3. The 'Glue' (Role Assignment): Granting the identity access to the Vault
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


output openAiEndpoint string = openAiAccount.properties.endpoint
output searchEndpoint string = 'https://${searchName}.search.windows.net'