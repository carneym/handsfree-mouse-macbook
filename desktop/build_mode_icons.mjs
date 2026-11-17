// Build only. npm install --prefix /tmp/headmouse-icon-build @resvg/resvg-js@2.6.2
// node desktop/build_mode_icons.mjs /tmp/headmouse-icon-build
import {createRequire} from 'node:module';
import {readFileSync,writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const require=createRequire(path.resolve(process.argv[2]||'.','package.json'));
const {Resvg}=require('@resvg/resvg-js');
const folder=path.join(path.dirname(fileURLToPath(import.meta.url)),'assets','lucide');
for(const name of ['mouse-pointer-click','hand','move','move-vertical','crosshair']){
  const svg=readFileSync(path.join(folder,name+'.svg'),'utf8').replaceAll('currentColor','#152b35');
  for(const scale of [1,2,3]){
    const result=new Resvg(svg,{font:{loadSystemFonts:false},fitTo:{mode:'width',value:17*scale}}).render();
    writeFileSync(path.join(folder,`${name}@${scale}x.png`),result.asPng());
  }
  console.log(name);
}
