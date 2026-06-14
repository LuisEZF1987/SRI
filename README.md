# dimed-sri

Módulo compartido de **facturación electrónica SRI (Ecuador)** para la suite Dimed.
Usado como submódulo (`billing/sri`) por: dimed-lis, dimed-ris, dimed-his, dimed-erp.

## Archivos
- `xml_builder.py` — construcción del XML del comprobante
- `signer.py` — firma electrónica (XAdES-BES)
- `ws_client.py` — cliente de los web services del SRI (recepción/autorización)
- `ride_pdf.py` — generación del RIDE (PDF)
- `ats.py` — Anexo Transaccional Simplificado

## Uso como submódulo
```bash
git clone --recursive git@github.com:LuisEZF1987/<PRODUCTO>.git
# o si ya clonaste:
git submodule update --init --recursive
```
Editar el SRI una vez aquí; luego en cada producto: `git submodule update --remote billing/sri && git commit`.
