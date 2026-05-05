import React from 'react'
import { Alert, Button, Descriptions, Drawer, Form, Input, InputNumber, Select, Space, Switch, Table, Tabs, Tag, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  disableAgentSkill,
  enableAgentSkill,
  exportAgentSkill,
  fetchAgentCapabilities,
  fetchAgentSkill,
  fetchAgentSkillAuditLogs,
  fetchAgentSkillVersions,
  fetchAgentSkills,
  rollbackAgentSkill,
  testAgentSkill,
  updateAgentSkill,
  type AgentCapability,
  type AgentSkillAuditLog,
  type AgentSkillDefinition,
  type AgentSkillVersionLog,
} from '../../api/agent'
import { AgentPageShell, AgentPanel } from './AgentPageLayout'

function riskColor(risk: string) {
  if (risk === 'critical' || risk === 'high') return 'red'
  if (risk === 'medium') return 'gold'
  return 'green'
}

function permissionLabel(permission: string) {
  return {
    read_only: '只读',
    write_draft: '草案写入',
    write_confirmed: '确认后写入',
    admin_only: '管理员',
  }[permission] || permission
}

export default function AgentSkillManagementPage() {
  const [skills, setSkills] = React.useState<AgentSkillDefinition[]>([])
  const [capabilities, setCapabilities] = React.useState<AgentCapability[]>([])
  const [loading, setLoading] = React.useState(false)
  const [ownerAgent, setOwnerAgent] = React.useState<string | undefined>()
  const [category, setCategory] = React.useState<string | undefined>()
  const [riskLevel, setRiskLevel] = React.useState<string | undefined>()
  const [enabled, setEnabled] = React.useState<boolean | null>(null)
  const [search, setSearch] = React.useState('')
  const [selected, setSelected] = React.useState<AgentSkillDefinition | null>(null)
  const [drawerOpen, setDrawerOpen] = React.useState(false)
  const [testing, setTesting] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [testReply, setTestReply] = React.useState<string | null>(null)
  const [versions, setVersions] = React.useState<AgentSkillVersionLog[]>([])
  const [auditLogs, setAuditLogs] = React.useState<AgentSkillAuditLog[]>([])
  const [form] = Form.useForm()

  const load = React.useCallback(async () => {
    setLoading(true)
    try {
      const [skillData, capabilityData] = await Promise.all([
        fetchAgentSkills({ ownerAgent, category, riskLevel, enabled }),
        fetchAgentCapabilities(),
      ])
      setSkills(skillData.items || [])
      setCapabilities(capabilityData.items || [])
    } catch (error_: any) {
      message.error(error_?.message || '加载 Agent Skill 失败')
    } finally {
      setLoading(false)
    }
  }, [ownerAgent, category, riskLevel, enabled])

  React.useEffect(() => { load() }, [load])

  const ownerOptions = React.useMemo(() => {
    const names = new Set<string>()
    capabilities.forEach(item => names.add(item.agentName))
    skills.forEach(item => names.add(item.ownerAgent))
    return Array.from(names).sort((left, right) => left.localeCompare(right)).map(value => ({ label: value, value }))
  }, [capabilities, skills])

  const categoryOptions = React.useMemo(() => {
    return Array.from(new Set(skills.map(item => item.category))).sort((left, right) => left.localeCompare(right)).map(value => ({ label: value, value }))
  }, [skills])

  const filteredSkills = React.useMemo(() => {
    const keyword = search.trim().toLowerCase()
    if (!keyword) return skills
    return skills.filter(item => [item.skillKey, item.skillName, item.description, item.ownerAgent, item.category].some(value => value.toLowerCase().includes(keyword)))
  }, [skills, search])

  const openDetail = async (row: AgentSkillDefinition) => {
    setDrawerOpen(true)
    setSelected(row)
    setTestReply(null)
    try {
      const [detail, versionData, auditData] = await Promise.all([
        fetchAgentSkill(row.skillKey),
        fetchAgentSkillVersions(row.skillKey).catch(() => ({ items: [], count: 0 })),
        fetchAgentSkillAuditLogs(row.skillKey).catch(() => ({ items: [], count: 0 })),
      ])
      setSelected(detail)
      setVersions(versionData.items || [])
      setAuditLogs(auditData.items || [])
      form.setFieldsValue({
        description: detail.description,
        plainExplanation: detail.plainExplanation,
        riskLevel: detail.riskLevel,
        timeoutMs: detail.timeoutMs,
        permission: detail.permission,
        requiresConfirmation: detail.requiresConfirmation,
        requiredDataSources: detail.requiredDataSources.join(', '),
        dependencies: detail.dependencies.join(', '),
        reason: '',
      })
    } catch (error_: any) {
      message.warning(error_?.message || '详情加载失败，使用列表数据')
    }
  }

  const runSkillStatusCheck = async () => {
    if (!selected) return
    setTesting(true)
    try {
      const response = await testAgentSkill(selected.skillKey, `测试 ${selected.skillName} Skill`)
      setTestReply(response.reply)
      if (response.requiresConfirmation) message.warning('该 Skill 相关操作需要确认')
      else message.success('已完成 Skill test-run')
    } catch (error_: any) {
      message.error(error_?.message || '测试调用失败')
    } finally {
      setTesting(false)
    }
  }

  const saveSkill = async () => {
    if (!selected) return
    try {
      const values = await form.validateFields()
      setSaving(true)
      const updated = await updateAgentSkill(selected.skillKey, {
        description: values.description,
        plainExplanation: values.plainExplanation,
        riskLevel: values.riskLevel,
        timeoutMs: values.timeoutMs,
        permission: values.permission,
        requiresConfirmation: !!values.requiresConfirmation,
        requiredDataSources: splitCsv(values.requiredDataSources),
        dependencies: splitCsv(values.dependencies),
        reason: values.reason || '前端 Skill 管理页面更新',
      })
      message.success('Skill 已保存并写入审计')
      await load()
      await openDetail(updated)
    } catch (error_: any) {
      if (!error_?.errorFields) message.error(error_?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const toggleSkill = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const updated = selected.enabled
        ? await disableAgentSkill(selected.skillKey, '前端 Skill 管理页面禁用')
        : await enableAgentSkill(selected.skillKey, '前端 Skill 管理页面启用')
      message.success(updated.enabled ? 'Skill 已启用' : 'Skill 已禁用')
      await load()
      await openDetail(updated)
    } catch (error_: any) {
      message.error(error_?.message || '启停失败')
    } finally {
      setSaving(false)
    }
  }

  const rollbackSkill = async (versionId: string) => {
    if (!selected) return
    setSaving(true)
    try {
      const updated = await rollbackAgentSkill(selected.skillKey, versionId, `前端回滚到历史版本 ${versionId}`)
      message.success('Skill 已回滚并写入审计')
      await load()
      await openDetail(updated)
    } catch (error_: any) {
      message.error(error_?.message || '回滚失败')
    } finally {
      setSaving(false)
    }
  }

  const exportSkill = async () => {
    if (!selected) return
    try {
      const payload = await exportAgentSkill(selected.skillKey)
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${selected.skillKey}-agent-skill.json`
      link.click()
      URL.revokeObjectURL(url)
      message.success('Skill JSON 已导出')
    } catch (error_: any) {
      message.error(error_?.message || '导出失败')
    }
  }

  const columns: ColumnsType<AgentSkillDefinition> = [
    {
      title: 'Skill',
      dataIndex: 'skillName',
      width: 260,
      render: (_, row) => (
        <div>
          <div style={{fontWeight:700, color:'var(--text)'}}>{row.skillName}</div>
          <div style={{fontSize:12, color:'var(--text-muted)'}}>{row.skillKey}</div>
        </div>
      ),
    },
    { title: 'Owner Agent', dataIndex: 'ownerAgent', width: 180, render: value => <Tag color="blue">{value}</Tag> },
    { title: '分类', dataIndex: 'category', width: 150 },
    { title: '风险', dataIndex: 'riskLevel', width: 90, render: value => <Tag color={riskColor(value)}>{value}</Tag> },
    { title: '权限', dataIndex: 'permission', width: 120, render: value => permissionLabel(value) },
    { title: '启用', dataIndex: 'enabled', width: 80, render: value => value ? <Tag color="green">ON</Tag> : <Tag>OFF</Tag> },
    { title: '版本', dataIndex: 'version', width: 90 },
    {
      title: '说明',
      dataIndex: 'description',
      ellipsis: true,
    },
    {
      title: '操作',
      width: 100,
      render: (_, row) => <Button size="small" onClick={() => openDetail(row)}>详情</Button>,
    },
  ]

  const highRiskCount = skills.filter(item => item.riskLevel === 'high' || item.riskLevel === 'critical').length
  const enabledCount = skills.filter(item => item.enabled).length

  return (
    <AgentPageShell
      title="Agent Skill 管理"
      subtitle="能力注册表、风险分级、数据源依赖、测试调用、版本记录和审计日志。"
      actions={(
        <>
          <Tag color="green">启用 {enabledCount}</Tag>
          <Tag color="red">高风险 {highRiskCount}</Tag>
          <Tag color="blue">Agent {capabilities.length}</Tag>
          <Button onClick={load} loading={loading}>刷新</Button>
        </>
      )}
    >

      <Alert
        type="success"
        showIcon
        message="Skill 支持持久化覆盖、启停、版本记录和审计日志。写入前请先执行数据库迁移 0003_agent_runtime.up.sql。"
      />

      <AgentPanel>
        <div className="agent-toolbar">
          <Input.Search value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索 Skill / Agent / 分类" allowClear style={{width:260}} />
          <Select allowClear placeholder="Owner Agent" value={ownerAgent} onChange={setOwnerAgent} options={ownerOptions} style={{width:190}} />
          <Select allowClear placeholder="分类" value={category} onChange={setCategory} options={categoryOptions} style={{width:170}} />
          <Select allowClear placeholder="风险" value={riskLevel} onChange={setRiskLevel} style={{width:130}} options={['low','medium','high','critical'].map(value => ({label:value, value}))} />
          <Select placeholder="启用状态" value={enabled === null ? 'all' : String(enabled)} onChange={value => setEnabled(value === 'all' ? null : value === 'true')} style={{width:130}} options={[{label:'全部', value:'all'}, {label:'启用', value:'true'}, {label:'禁用', value:'false'}]} />
        </div>
        <Table<AgentSkillDefinition>
          rowKey="skillKey"
          loading={loading}
          columns={columns}
          dataSource={filteredSkills}
          size="small"
          pagination={{pageSize:10}}
        />
      </AgentPanel>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} width={780} title={selected?.skillName || 'Skill 详情'} destroyOnHidden>
        {selected && (
          <div style={{display:'flex', flexDirection:'column', gap:12}}>
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="Skill Key">{selected.skillKey}</Descriptions.Item>
              <Descriptions.Item label="Owner Agent">{selected.ownerAgent}</Descriptions.Item>
              <Descriptions.Item label="分类">{selected.category}</Descriptions.Item>
              <Descriptions.Item label="风险"><Tag color={riskColor(selected.riskLevel)}>{selected.riskLevel}</Tag></Descriptions.Item>
              <Descriptions.Item label="权限">{permissionLabel(selected.permission)}</Descriptions.Item>
              <Descriptions.Item label="确认要求">{selected.requiresConfirmation ? '需要确认' : '不需要确认'}</Descriptions.Item>
              <Descriptions.Item label="超时">{selected.timeoutMs} ms</Descriptions.Item>
              <Descriptions.Item label="版本">{selected.version}</Descriptions.Item>
              <Descriptions.Item label="说明">{selected.plainExplanation || selected.description}</Descriptions.Item>
              <Descriptions.Item label="数据源">{selected.requiredDataSources.length ? selected.requiredDataSources.map(item => <Tag key={item}>{item}</Tag>) : '-'}</Descriptions.Item>
              <Descriptions.Item label="依赖">{selected.dependencies.length ? selected.dependencies.map(item => <Tag key={item}>{item}</Tag>) : '-'}</Descriptions.Item>
            </Descriptions>
            <Space wrap>
              <Button type="primary" onClick={runSkillStatusCheck} loading={testing}>测试 Skill</Button>
              <Button danger={selected.enabled} onClick={toggleSkill} loading={saving}>{selected.enabled ? '禁用' : '启用'}</Button>
              <Button onClick={exportSkill}>导出 JSON</Button>
              {selected.requiresConfirmation && <Tag color="gold">写操作会进入确认流</Tag>}
            </Space>
            {testReply && <Alert type="success" showIcon message={testReply} />}
            <Tabs
              items={[
                {
                  key: 'edit',
                  label: '配置编辑',
                  children: (
                    <Form form={form} layout="vertical">
                      <Form.Item name="description" label="描述" rules={[{required:true, message:'请填写描述'}]}><Input.TextArea autoSize={{minRows:2, maxRows:4}} /></Form.Item>
                      <Form.Item name="plainExplanation" label="用户可读说明" rules={[{required:true, message:'请填写用户可读说明'}]}><Input.TextArea autoSize={{minRows:2, maxRows:4}} /></Form.Item>
                      <Space wrap style={{width:'100%'}}>
                        <Form.Item name="riskLevel" label="风险等级" rules={[{required:true}]}><Select style={{width:150}} options={['low','medium','high','critical'].map(value => ({label:value, value}))} /></Form.Item>
                        <Form.Item name="permission" label="权限" rules={[{required:true}]}><Select style={{width:170}} options={['read_only','write_draft','write_confirmed','admin_only'].map(value => ({label:permissionLabel(value), value}))} /></Form.Item>
                        <Form.Item name="timeoutMs" label="超时 ms" rules={[{required:true}]}><InputNumber min={1000} max={300000} style={{width:140}} /></Form.Item>
                        <Form.Item name="requiresConfirmation" label="需要确认" valuePropName="checked"><Switch /></Form.Item>
                      </Space>
                      <Form.Item name="requiredDataSources" label="数据源（逗号分隔）"><Input /></Form.Item>
                      <Form.Item name="dependencies" label="依赖（逗号分隔）"><Input /></Form.Item>
                      <Form.Item name="reason" label="变更原因"><Input placeholder="用于审计日志" /></Form.Item>
                      <Button type="primary" onClick={saveSkill} loading={saving}>保存配置</Button>
                    </Form>
                  ),
                },
                {
                  key: 'versions',
                  label: `版本 ${versions.length}`,
                  children: <Table rowKey="versionId" size="small" dataSource={versions} pagination={false} columns={[
                    {title:'版本', dataIndex:'version', width:90},
                    {title:'创建人', dataIndex:'createdBy', width:100},
                    {title:'摘要', dataIndex:'changeSummary'},
                    {title:'时间', dataIndex:'createdAt', width:180, render:(value:string) => value?.slice(0, 19).replace('T', ' ') || '-'},
                    {title:'操作', dataIndex:'versionId', width:90, render:(value:string) => <Button size="small" danger loading={saving} onClick={() => rollbackSkill(value)}>回滚</Button>},
                  ] as any} />,
                },
                {
                  key: 'audit',
                  label: `审计 ${auditLogs.length}`,
                  children: <Table rowKey="auditLogId" size="small" dataSource={auditLogs} pagination={false} columns={[
                    {title:'动作', dataIndex:'action', width:90},
                    {title:'结果', dataIndex:'result', width:90, render:(value:string) => <Tag color={value === 'success' ? 'green' : 'red'}>{value}</Tag>},
                    {title:'风险', dataIndex:'riskLevel', width:90, render:(value:string) => <Tag color={riskColor(value)}>{value}</Tag>},
                    {title:'原因', dataIndex:'reason'},
                    {title:'时间', dataIndex:'timestamp', width:180, render:(value:string) => value?.slice(0, 19).replace('T', ' ') || '-'},
                  ] as any} />,
                },
              ]}
            />
          </div>
        )}
      </Drawer>
    </AgentPageShell>
  )
}

function splitCsv(value?: string) {
  return String(value || '').split(',').map(item => item.trim()).filter(Boolean)
}