###To get all skills for the user ID #1:
Request:

```
curl "http://localhost:5000/api/account/1/skill" -b session=95e6cc42-4041-4cfb-bfe0-880107b07a75 -H "X-Requested-With: xmlhttprequest"
```

Response:

```
{"data":[{"id":2,"skill_name":"SomeSkill"}],"meta":{"total":1}}
```

###To create new skill item for logged user:
Request:

```
curl -d 'skill_name=English' "http://localhost:5000/api/account/skill" -b session=95e6cc42-4041-4cfb-bfe0-880107b07a75 -H "X-Requested-With: xmlhttprequest"
```

Response:

```
if error:
{"error":{"message":"You already have this skill"}}

if ok:
{} 
```

###To delete skill from logged user:
Request:

```
curl -d '{"id": 1}'  "http://localhost:5000/api/account/skill/delete" -b session=95e6cc42-4041-4cfb-bfe0-880107b07a75 -H "X-Requested-With: xmlhttprequest" -H "Content-Type: application/json"

```

Response:

```
{}
```