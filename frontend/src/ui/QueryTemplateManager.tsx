import React, { useEffect, useMemo, useState } from 'react'
import { buildApiUrl, API_ENDPOINTS } from '../config/api'
import { Table, Button, Modal, Form, Input, Select, Switch, Space, message, Popconfirm, Tag, Alert, Divider, List } from 'antd'

interface QueryTemplate {
  id: number
  scope: 'global' | 'symbol' | 'industry'
  target?: string | null
  template: string
  enabled: boolean
  priority: number
  notes?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export default function QueryTemplateManager(){
  const [data, setData] = useState<QueryTemplate[]>([])
  const [loading, setLoading] = useState(false)
  const [visible, setVisible] = useState(false)
  const [editing, setEditing] = useState<QueryTemplate | null>(null)
  const [form] = Form.useForm()
  const [testVisible, setTestVisible] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{built_query:string, total_count:number, results:Array<{title?:string, url?:string, published?:string, source?:string}>} | null>(null)
  const [testForm] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try{
      const r = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.QUERY_TEMPLATES_LIST))
      if(!r.ok) throw new Error(await r.text())
      const j = await r.json()
      setData(j.items || [])
    }catch(e:any){
      message.error(e.message || '加载失败')
    }finally{
      setLoading(false)
    }
  }

  useEffect(()=>{ load() },[])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ scope: 'global', enabled: true, priority: 5 })
    setVisible(true)
  }
  const openEdit = (row: QueryTemplate) => {
    setEditing(row)
    form.setFieldsValue({
      scope: row.scope,
      target: row.target || undefined,
      template: row.template,
      enabled: row.enabled,
      priority: row.priority,
      notes: row.notes || undefined,
    })
    setVisible(true)
  }

  const openTest = (row?: QueryTemplate) => {
    const tpl = row?.template || form.getFieldValue('template') || ''
    if(!tpl){
      message.warning('请先填写模板')
      return
    }
    setTestResult(null)
    testForm.resetFields()
    testForm.setFieldsValue({ template: tpl, max_results: 10 })
    setTestVisible(true)
  }

  const doTest = async () => {
    try{
      const v = await testForm.validateFields()
      setTesting(true)
      const r = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.QUERY_TEMPLATES_TEST),{
        method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({
          template: v.template,
          symbol: v.symbol||undefined,
          name: v.name||undefined,
          industry: v.industry||undefined,
          extra_keywords: v.extra_keywords||undefined,
          time_range: v.time_range||undefined,
          max_results: Number(v.max_results)||10,
          language: v.language||undefined,
          engines: v.engines||undefined,
        })
      })
      if(!r.ok) throw new Error(await r.text())
      const j = await r.json()
      setTestResult(j)
    }catch(e:any){
      if(e?.errorFields) return
      message.error(e.message||'测试失败')
    }finally{
      setTesting(false)
    }
  }

  const handleSubmit = async () => {
    try{
      const v = await form.validateFields()
      const payload = {
        scope: v.scope,
        target: v.target || null,
        template: v.template,
        enabled: !!v.enabled,
        priority: Number(v.priority)||0,
        notes: v.notes || null,
      }
      if(editing){
        const r = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.QUERY_TEMPLATES_UPDATE(editing.id)),{
          method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)
        })
        if(!r.ok) throw new Error(await r.text())
        message.success('已更新')
      }else{
        const r = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.QUERY_TEMPLATES_CREATE),{
          method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)
        })
        if(!r.ok) throw new Error(await r.text())
        message.success('已创建')
      }
      setVisible(false)
      load()
    }catch(e:any){
      if(e?.errorFields) return
      message.error(e.message || '提交失败')
    }
  }

  const handleDelete = async (row: QueryTemplate) => {
    try{
      const r = await fetch(buildApiUrl(API_ENDPOINTS.NEWS.QUERY_TEMPLATES_DELETE(row.id)), { method:'DELETE' })
      if(!r.ok) throw new Error(await r.text())
      message.success('已删除')
      load()
    }catch(e:any){
      message.error(e.message || '删除失败')
    }
  }

  const columns = [
    { title: 'ID', dataIndex:'id', width:70 },
    { title: 'Scope', dataIndex:'scope', width:90, render:(v:string)=>{
      const color = v==='global'?'blue': v==='symbol'?'purple':'cyan'
      return <Tag color={color}>{v}</Tag>
    }},
    { title: 'Target', dataIndex:'target', width:140, render:(v:string)=> v|| '-' },
    { title: 'Template', dataIndex:'template', ellipsis:true },
    { title: 'Enabled', dataIndex:'enabled', width:90, render:(v:boolean)=> v? <Tag color='green'>on</Tag>:<Tag>off</Tag>},
    { title: 'Priority', dataIndex:'priority', width:90 },
    { title: 'Notes', dataIndex:'notes', ellipsis:true },
    { title: 'Actions', key:'actions', width:220, render: (_:any, row:QueryTemplate)=> (
      <Space>
        <Button size='small' onClick={()=> openTest(row)}>测试</Button>
        <Button size='small' onClick={()=> openEdit(row)}>编辑</Button>
        <Popconfirm title='确认删除?' onConfirm={()=> handleDelete(row)}>
          <Button size='small' danger>删除</Button>
        </Popconfirm>
      </Space>
    ) }
  ]

  return (
    <div style={{minHeight:'100vh', background:'var(--surface-dark)'}}>
      <div style={{maxWidth:980, margin:'0 auto', padding:24}}>
        <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:12}}>
          <div>
            <div style={{fontSize:12, color:'var(--text-muted)'}}>新闻 · 查询范式</div>
            <h2 style={{margin:0, color:'var(--text)'}}>Query 模板管理</h2>
          </div>
          <Button type='primary' onClick={openCreate}>新增模板</Button>
        </div>
        <Table<QueryTemplate>
          rowKey='id'
          columns={columns as any}
          loading={loading}
          dataSource={data}
          pagination={{ pageSize: 10 }}
        />
      </div>

      <Modal open={visible} title={editing?`编辑模板 #${editing.id}`:'新建模板'} onCancel={()=> setVisible(false)} onOk={handleSubmit} destroyOnClose>
        <Form layout='vertical' form={form} preserve={false}>
          <Alert type='info' showIcon style={{marginBottom:12}} message={
            <div>
              <div>模板支持保留占位符：{'{symbol}'}, {'{name}'}, {'{industry}'}（至少包含其一）。</div>
              <div>示例：<code>{'{symbol} OR {name} (公告 OR 舆情 OR 经营)'}</code></div>
            </div>
          }/>
          <Form.Item name='scope' label='作用域' rules={[{required:true}]}>
            <Select options={[
              {label:'global (全局)', value:'global'},
              {label:'symbol (个股)', value:'symbol'},
              {label:'industry (行业)', value:'industry'},
            ]} />
          </Form.Item>
          <Form.Item name='target' label='目标 (scope=symbol/industry 时可填)'>
            <Input placeholder='600519.SH 或 新能源' />
          </Form.Item>
          <Form.Item name='template' label='模板' rules={[{required:true}]}> 
            <Input.TextArea autoSize={{minRows:2, maxRows:4}} placeholder='{symbol} 公告 或 {name} 舆情' />
          </Form.Item>
          <Form.Item name='extra_keywords' label='自定义关键字 (可选)'>
            <Input placeholder='以空格或逗号分隔，例如：订单 产能 扩产' />
          </Form.Item>
          <Form.Item name='priority' label='优先级'>
            <Input type='number' />
          </Form.Item>
          <Form.Item name='enabled' label='启用' valuePropName='checked'>
            <Switch />
          </Form.Item>
          <Form.Item name='notes' label='备注'>
            <Input.TextArea autoSize={{minRows:1, maxRows:3}} />
          </Form.Item>
          <Divider />
          <Space>
            <Button onClick={()=> openTest()} disabled={!form.getFieldValue('template')}>测试当前模板</Button>
          </Space>
        </Form>
      </Modal>

      <Modal open={testVisible} title='模板测试' width={820} onCancel={()=> setTestVisible(false)} onOk={doTest} okText='执行测试' confirmLoading={testing} destroyOnClose>
        <Form layout='vertical' form={testForm} preserve={false}>
          <Form.Item name='template' label='模板' rules={[{required:true}]}> 
            <Input.TextArea autoSize={{minRows:2, maxRows:4}} />
          </Form.Item>
          <Space style={{display:'flex'}} wrap>
            <Form.Item name='symbol' label='symbol'>
              <Input placeholder='例如 600519.SH' style={{width:180}}/>
            </Form.Item>
            <Form.Item name='name' label='name'>
              <Input placeholder='例如 贵州茅台' style={{width:180}}/>
            </Form.Item>
            <Form.Item name='industry' label='industry'>
              <Input placeholder='例如 白酒' style={{width:180}}/>
            </Form.Item>
          </Space>
          <Form.Item name='extra_keywords' label='自定义关键字'>
            <Input placeholder='以空格或逗号分隔' />
          </Form.Item>
          <Space style={{display:'flex'}} wrap>
            <Form.Item name='time_range' label='时间范围'>
              <Input placeholder="如 7d / 30d" style={{width:160}}/>
            </Form.Item>
            <Form.Item name='max_results' label='返回条数'>
              <Input type='number' style={{width:120}}/>
            </Form.Item>
            <Form.Item name='language' label='语言'>
              <Input placeholder='如 zh-CN' style={{width:140}}/>
            </Form.Item>
            <Form.Item name='engines' label='引擎覆盖'>
              <Input placeholder='如 bing news,google news' style={{width:240}}/>
            </Form.Item>
          </Space>
        </Form>
        {testResult && (
          <div>
            <Alert type='success' showIcon message={<span>构建查询：<code>{testResult.built_query}</code>；返回 {testResult.total_count} 条</span>} style={{marginBottom:12}}/>
            <List
              size='small'
              dataSource={testResult.results}
              renderItem={(it)=> (
                <List.Item>
                  <div>
                    <div style={{fontWeight:500}}>{it.title||'(无标题)'}</div>
                    <div style={{fontSize:12, color:'#6b7280'}}>{it.source||''} · {it.published||''}</div>
                    <a href={it.url} target='_blank' rel='noreferrer'>{it.url}</a>
                  </div>
                </List.Item>
              )}
            />
          </div>
        )}
      </Modal>
    </div>
  )
}
